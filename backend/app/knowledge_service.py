from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy 随 pandas 一起安装，正常环境必然存在
    np = None  # type: ignore[assignment]


DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "data"
DATABASE_PATH = DATA_DIRECTORY / "exam_booster.db"
EMBEDDING_CACHE_PATH = DATA_DIRECTORY / "embedding_cache.db"
EMBEDDING_CONFIG_KEY = "embedding_config"
DEFAULT_EMBEDDING_CONFIG: dict[str, Any] = {
    "enabled": True,
    "provider": "ollama",
    "baseUrl": "http://127.0.0.1:11434",
    "model": "bge-m3",
}
_EMBEDDING_UNAVAILABLE_UNTIL = 0.0
_OLLAMA_START_LOCK = threading.Lock()
_LOCAL_OLLAMA_PROCESS: subprocess.Popen | None = None
_LOCAL_OLLAMA_EXECUTABLE = Path(
    os.environ.get("EXAM_BOOSTER_OLLAMA_EXECUTABLE", r"D:\AI\Ollama\ollama.exe")
)
_LOCAL_OLLAMA_MODELS = Path(
    os.environ.get("OLLAMA_MODELS", r"D:\AI\Models\text\ollama")
)
_LOCAL_OLLAMA_LOG_DIRECTORY = _LOCAL_OLLAMA_EXECUTABLE.parent / "logs"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _database_connection() -> sqlite3.Connection:
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def _embedding_connection() -> sqlite3.Connection:
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(EMBEDDING_CACHE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_knowledge_database() -> None:
    with _database_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_materials (
                course_id TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                name TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                character_count INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (course_id, relative_path)
            );

            CREATE TABLE IF NOT EXISTS material_chunks (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                material_name TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                locator TEXT NOT NULL,
                heading TEXT NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_material_chunks_course
                ON material_chunks (course_id, relative_path, chunk_index);

            CREATE TABLE IF NOT EXISTS chat_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                external_id TEXT UNIQUE,
                course_id TEXT NOT NULL,
                role TEXT NOT NULL,
                conversation_mode TEXT NOT NULL DEFAULT 'chat',
                content TEXT NOT NULL,
                sources_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chat_turns_course
                ON chat_turns (course_id, id DESC);

            CREATE TABLE IF NOT EXISTS learning_events (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                knowledge_point_id TEXT NOT NULL DEFAULT '',
                question_id TEXT NOT NULL DEFAULT '',
                is_correct INTEGER,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_learning_events_course
                ON learning_events (course_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS learner_memories (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                knowledge_point_id TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                confidence REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                source_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_learner_memories_course
                ON learner_memories (course_id, status, updated_at DESC);

            CREATE TABLE IF NOT EXISTS memory_evidence (
                memory_id TEXT NOT NULL,
                evidence_type TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (memory_id, evidence_type, evidence_id),
                FOREIGN KEY (memory_id) REFERENCES learner_memories(id)
            );

            CREATE TABLE IF NOT EXISTS review_sections (
                course_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                section_index INTEGER NOT NULL,
                section_key TEXT NOT NULL,
                title TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY (course_id, task_id, section_index)
            );

            -- 分层对话记忆：把已被压缩的早期对话区间持久化为脉络摘要，
            -- 配合 recent_chat_messages（近期原文窗口）与 related_chat_history（相关性检索）使用。
            CREATE TABLE IF NOT EXISTS chat_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id TEXT NOT NULL,
                conversation_mode TEXT NOT NULL DEFAULT 'chat',
                content TEXT NOT NULL,
                from_turn_id INTEGER NOT NULL,
                to_turn_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chat_summaries_course
                ON chat_summaries (course_id, conversation_mode, id DESC);
            """
        )
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(chat_turns)").fetchall()
        }
        if "conversation_mode" not in columns:
            connection.execute(
                "ALTER TABLE chat_turns ADD COLUMN conversation_mode TEXT NOT NULL DEFAULT 'chat'"
            )
        try:
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS material_chunks_fts
                USING fts5(chunk_id UNINDEXED, course_id UNINDEXED, content, tokenize='unicode61')
                """
            )
        except sqlite3.OperationalError:
            pass

    with _embedding_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS chunk_embeddings (
                chunk_id TEXT NOT NULL,
                model TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                dimension INTEGER NOT NULL,
                vector_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (chunk_id, model)
            );
            CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_model
                ON chunk_embeddings (model);
            CREATE TABLE IF NOT EXISTS memory_embeddings (
                memory_id TEXT NOT NULL,
                model TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                dimension INTEGER NOT NULL,
                vector_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (memory_id, model)
            );
            CREATE INDEX IF NOT EXISTS idx_memory_embeddings_model
                ON memory_embeddings (model);
            """
        )


def _read_embedding_config() -> dict[str, Any]:
    initialize_knowledge_database()
    with _database_connection() as connection:
        row = connection.execute(
            "SELECT value FROM app_metadata WHERE key = ?",
            (EMBEDDING_CONFIG_KEY,),
        ).fetchone()
    if row is None:
        return dict(DEFAULT_EMBEDDING_CONFIG)
    try:
        saved = json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        saved = {}
    return {**DEFAULT_EMBEDDING_CONFIG, **saved}


def save_embedding_config(payload: dict[str, Any]) -> dict[str, Any]:
    base_url = str(payload.get("baseUrl") or payload.get("base_url") or "").strip().rstrip("/")
    parsed_url = urlparse(base_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        raise ValueError("Embedding Base URL 必须是合法的 HTTP 或 HTTPS 地址")
    model = str(payload.get("model") or "").strip()
    if not model:
        raise ValueError("请填写 Embedding 模型名")
    config = {
        "enabled": bool(payload.get("enabled", True)),
        "provider": "ollama",
        "baseUrl": base_url,
        "model": model,
    }
    initialize_knowledge_database()
    with _database_connection() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO app_metadata (key, value) VALUES (?, ?)",
            (EMBEDDING_CONFIG_KEY, json.dumps(config, ensure_ascii=False)),
        )
    return get_embedding_status(probe=False)


def _perform_ollama_request(
    config: dict[str, Any],
    path: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    url = f"{str(config['baseUrl']).rstrip('/')}{path}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method="POST" if body is not None else "GET",
    )
    with urlopen(request, timeout=None) as response:
        return json.loads(response.read().decode("utf-8"))


def _is_local_ollama_config(config: dict[str, Any]) -> bool:
    parsed_url = urlparse(str(config.get("baseUrl", "")))
    return parsed_url.scheme == "http" and parsed_url.hostname in {"127.0.0.1", "localhost", "::1"}


def _start_local_ollama_service(config: dict[str, Any], *, wait: bool) -> bool:
    global _LOCAL_OLLAMA_PROCESS

    if not config.get("enabled") or not _is_local_ollama_config(config):
        return False
    if not _LOCAL_OLLAMA_EXECUTABLE.is_file():
        return False

    with _OLLAMA_START_LOCK:
        try:
            _perform_ollama_request(config, "/api/tags")
            return True
        except (URLError, TimeoutError, OSError):
            pass

        process = _LOCAL_OLLAMA_PROCESS
        if process is None or process.poll() is not None:
            _LOCAL_OLLAMA_LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
            environment = os.environ.copy()
            environment["OLLAMA_HOST"] = str(urlparse(str(config["baseUrl"])).netloc)
            environment["OLLAMA_MODELS"] = str(_LOCAL_OLLAMA_MODELS)
            environment["OLLAMA_NO_CLOUD"] = "true"
            creation_flags = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
                | subprocess.DETACHED_PROCESS
            )
            stdout_path = _LOCAL_OLLAMA_LOG_DIRECTORY / "server.stdout.log"
            stderr_path = _LOCAL_OLLAMA_LOG_DIRECTORY / "server.stderr.log"
            with stdout_path.open("ab") as stdout_log, stderr_path.open("ab") as stderr_log:
                process = subprocess.Popen(
                    [str(_LOCAL_OLLAMA_EXECUTABLE), "serve"],
                    cwd=str(_LOCAL_OLLAMA_EXECUTABLE.parent),
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_log,
                    stderr=stderr_log,
                    creationflags=creation_flags,
                    close_fds=True,
                )
            _LOCAL_OLLAMA_PROCESS = process

        if not wait:
            return True

        while True:
            try:
                _perform_ollama_request(config, "/api/tags")
                return True
            except (URLError, TimeoutError, OSError):
                if process.poll() is not None:
                    raise RuntimeError(f"Ollama 启动失败，进程退出码为 {process.returncode}")
                time.sleep(0.25)


def ensure_local_ollama_service() -> bool:
    return _start_local_ollama_service(_read_embedding_config(), wait=False)


def _ollama_request(path: str, payload: dict[str, Any] | None = None) -> Any:
    config = _read_embedding_config()
    try:
        return _perform_ollama_request(config, path, payload)
    except (URLError, TimeoutError, OSError):
        if not _start_local_ollama_service(config, wait=True):
            raise
        return _perform_ollama_request(config, path, payload)


def _request_embeddings(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    config = _read_embedding_config()
    if not config.get("enabled"):
        raise RuntimeError("Embedding 已关闭")
    try:
        data = _ollama_request(
            "/api/embed",
            {"model": config["model"], "input": texts},
        )
        embeddings = data.get("embeddings") if isinstance(data, dict) else None
        if isinstance(embeddings, list) and len(embeddings) == len(texts):
            return [[float(value) for value in vector] for vector in embeddings]
    except HTTPError as error:
        if error.code != 404:
            raise

    vectors: list[list[float]] = []
    for text in texts:
        data = _ollama_request(
            "/api/embeddings",
            {"model": config["model"], "prompt": text},
        )
        vector = data.get("embedding") if isinstance(data, dict) else None
        if not isinstance(vector, list) or not vector:
            raise RuntimeError("Embedding 服务没有返回向量")
        vectors.append([float(value) for value in vector])
    return vectors


def _embedding_counts(model: str) -> tuple[int, int, int]:
    with _database_connection() as connection:
        total = int(connection.execute("SELECT COUNT(*) FROM material_chunks").fetchone()[0])
    with _embedding_connection() as connection:
        row = connection.execute(
            "SELECT COUNT(*), COALESCE(MAX(dimension), 0) FROM chunk_embeddings WHERE model = ?",
            (model,),
        ).fetchone()
    return int(row[0]), total, int(row[1])


def get_embedding_status(*, probe: bool = True) -> dict[str, Any]:
    config = _read_embedding_config()
    indexed, total, dimension = _embedding_counts(str(config["model"]))
    result = {
        **config,
        "status": "disabled" if not config.get("enabled") else "unavailable",
        "message": "Embedding 已关闭，当前使用关键词检索。" if not config.get("enabled") else "尚未检测服务。",
        "indexedChunks": indexed,
        "totalChunks": total,
        "dimension": dimension,
    }
    if not config.get("enabled") or not probe:
        return result
    try:
        data = _ollama_request("/api/tags")
        names = [str(item.get("name", "")) for item in data.get("models", []) if isinstance(item, dict)]
        selected = str(config["model"])
        available = any(name == selected or name.split(":", 1)[0] == selected.split(":", 1)[0] for name in names)
        if not available:
            result["message"] = f"Ollama 已连接，但未发现模型 {selected}。"
            return result
        result["status"] = "ready"
        result["message"] = "Embedding 可用，语义检索已启用。"
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        result["message"] = "Ollama 未连接，当前自动使用关键词检索。"
    return result


def test_embedding_connection() -> dict[str, Any]:
    config = _read_embedding_config()
    if not config.get("enabled"):
        return {**get_embedding_status(probe=False), "success": True}
    try:
        vectors = _request_embeddings(["期末复习知识库连接测试"])
        dimension = len(vectors[0]) if vectors else 0
        return {
            **get_embedding_status(probe=False),
            "success": dimension > 0,
            "status": "ready" if dimension > 0 else "unavailable",
            "message": f"连接成功，向量维度 {dimension}。" if dimension else "服务未返回有效向量。",
            "dimension": dimension,
        }
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError) as error:
        return {
            **get_embedding_status(probe=False),
            "success": False,
            "status": "unavailable",
            "message": f"Embedding 连接失败：{error}",
        }


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _split_long_text(text: str, limit: int = 900) -> list[str]:
    if len(text) <= limit:
        return [text]
    sentences = [item.strip() for item in re.split(r"(?<=[。！？；.!?;])", text) if item.strip()]
    parts: list[str] = []
    current = ""
    for sentence in sentences or [text]:
        if current and len(current) + len(sentence) > limit:
            parts.append(current)
            current = ""
        if len(sentence) > limit:
            parts.extend(sentence[index : index + limit] for index in range(0, len(sentence), limit))
        else:
            current += sentence
    if current:
        parts.append(current)
    return parts


def _chunk_document(text: str) -> list[dict[str, str]]:
    normalized = _normalize_text(text)
    if not normalized:
        return []
    blocks: list[str] = []
    for line in normalized.split("\n"):
        blocks.extend(_split_long_text(line))

    chunks: list[dict[str, str]] = []
    current: list[str] = []
    current_length = 0
    heading = ""
    for block in blocks:
        is_heading = len(block) <= 48 and bool(re.match(r"^(第?[一二三四五六七八九十百0-9]+[章节部分页、.．]|[一二三四五六七八九十]+、|\d+[.．])", block))
        if is_heading:
            heading = block
        if current and current_length + len(block) > 1000:
            content = "\n".join(current).strip()
            chunks.append({"heading": heading, "content": content})
            overlap = content[-120:] if len(content) > 120 else ""
            current = [overlap] if overlap else []
            current_length = len(overlap)
        current.append(block)
        current_length += len(block)
    if current:
        content = "\n".join(current).strip()
        if content:
            chunks.append({"heading": heading, "content": content})

    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for chunk in chunks:
        fingerprint = _content_hash(chunk["content"])
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(chunk)
    return unique


def sync_material_documents(course_id: str, documents: list[dict[str, str]]) -> dict[str, int]:
    initialize_knowledge_database()
    normalized_documents = []
    for document in documents:
        relative_path = str(document.get("relativePath", "")).strip()
        text = _normalize_text(str(document.get("text", "")))
        if relative_path:
            normalized_documents.append(
                {
                    "relativePath": relative_path,
                    "name": str(document.get("name") or Path(relative_path).name),
                    "text": text,
                    "contentHash": _content_hash(text),
                }
            )

    removed_chunk_ids: list[str] = []
    changed_count = 0
    with _database_connection() as connection:
        existing = {
            row["relative_path"]: row["content_hash"]
            for row in connection.execute(
                "SELECT relative_path, content_hash FROM knowledge_materials WHERE course_id = ?",
                (course_id,),
            )
        }
        current_paths = {item["relativePath"] for item in normalized_documents}
        stale_paths = set(existing) - current_paths
        for relative_path in stale_paths:
            rows = connection.execute(
                "SELECT id FROM material_chunks WHERE course_id = ? AND relative_path = ?",
                (course_id, relative_path),
            ).fetchall()
            stale_ids = [str(row["id"]) for row in rows]
            removed_chunk_ids.extend(stale_ids)
            if stale_ids:
                try:
                    connection.executemany(
                        "DELETE FROM material_chunks_fts WHERE chunk_id = ?",
                        [(chunk_id,) for chunk_id in stale_ids],
                    )
                except sqlite3.OperationalError:
                    pass
            connection.execute(
                "DELETE FROM material_chunks WHERE course_id = ? AND relative_path = ?",
                (course_id, relative_path),
            )
            connection.execute(
                "DELETE FROM knowledge_materials WHERE course_id = ? AND relative_path = ?",
                (course_id, relative_path),
            )

        for document in normalized_documents:
            relative_path = document["relativePath"]
            if existing.get(relative_path) == document["contentHash"]:
                continue
            changed_count += 1
            old_rows = connection.execute(
                "SELECT id FROM material_chunks WHERE course_id = ? AND relative_path = ?",
                (course_id, relative_path),
            ).fetchall()
            old_ids = [str(row["id"]) for row in old_rows]
            removed_chunk_ids.extend(old_ids)
            if old_ids:
                try:
                    connection.executemany(
                        "DELETE FROM material_chunks_fts WHERE chunk_id = ?",
                        [(chunk_id,) for chunk_id in old_ids],
                    )
                except sqlite3.OperationalError:
                    pass
            connection.execute(
                "DELETE FROM material_chunks WHERE course_id = ? AND relative_path = ?",
                (course_id, relative_path),
            )
            for index, chunk in enumerate(_chunk_document(document["text"]), start=1):
                chunk_hash = _content_hash(chunk["content"])
                chunk_id = hashlib.sha256(
                    f"{course_id}|{relative_path}|{index}|{chunk_hash}".encode("utf-8")
                ).hexdigest()[:32]
                heading = chunk["heading"]
                locator = heading or f"第 {index} 段"
                connection.execute(
                    """
                    INSERT INTO material_chunks (
                        id, course_id, relative_path, material_name, chunk_index,
                        locator, heading, content, content_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        course_id,
                        relative_path,
                        document["name"],
                        index,
                        locator,
                        heading,
                        chunk["content"],
                        chunk_hash,
                        _now(),
                    ),
                )
                try:
                    connection.execute(
                        "INSERT INTO material_chunks_fts (chunk_id, course_id, content) VALUES (?, ?, ?)",
                        (chunk_id, course_id, chunk["content"]),
                    )
                except sqlite3.OperationalError:
                    pass
            connection.execute(
                """
                INSERT OR REPLACE INTO knowledge_materials (
                    course_id, relative_path, name, content_hash, character_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    course_id,
                    relative_path,
                    document["name"],
                    document["contentHash"],
                    len(document["text"]),
                    _now(),
                ),
            )

        chunk_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM material_chunks WHERE course_id = ?",
                (course_id,),
            ).fetchone()[0]
        )

    if removed_chunk_ids:
        with _embedding_connection() as connection:
            connection.executemany(
                "DELETE FROM chunk_embeddings WHERE chunk_id = ?",
                [(chunk_id,) for chunk_id in removed_chunk_ids],
            )
        _invalidate_vector_cache()
    return {"materials": len(normalized_documents), "chunks": chunk_count, "changed": changed_count}


def rebuild_course_embeddings(course_id: str) -> dict[str, Any]:
    config = _read_embedding_config()
    if not config.get("enabled"):
        raise RuntimeError("Embedding 已关闭")
    with _database_connection() as connection:
        rows = connection.execute(
            "SELECT id, content, content_hash FROM material_chunks WHERE course_id = ? ORDER BY relative_path, chunk_index",
            (course_id,),
        ).fetchall()
    if not rows:
        return {**get_embedding_status(probe=False), "status": "ready", "message": "资料库暂无可索引文字。"}

    model = str(config["model"])
    with _embedding_connection() as connection:
        cached = {
            row["chunk_id"]: row["content_hash"]
            for row in connection.execute(
                "SELECT chunk_id, content_hash FROM chunk_embeddings WHERE model = ?",
                (model,),
            )
        }
    pending = [row for row in rows if cached.get(row["id"]) != row["content_hash"]]
    for start in range(0, len(pending), 16):
        batch = pending[start : start + 16]
        vectors = _request_embeddings([str(row["content"]) for row in batch])
        with _embedding_connection() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO chunk_embeddings (
                    chunk_id, model, content_hash, dimension, vector_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["id"],
                        model,
                        row["content_hash"],
                        len(vector),
                        json.dumps(vector, separators=(",", ":")),
                        _now(),
                    )
                    for row, vector in zip(batch, vectors, strict=True)
                ],
            )
    _invalidate_vector_cache(model)
    status = get_embedding_status(probe=False)
    return {
        **status,
        "status": "ready",
        "message": f"向量索引已更新，本次新增或刷新 {len(pending)} 个分块。",
    }


def _query_terms(query: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9][A-Za-z0-9_+.-]{1,}|[\u4e00-\u9fff]{2,}", query.lower())
    expanded: list[str] = []
    for term in terms:
        expanded.append(term)
        if re.fullmatch(r"[\u4e00-\u9fff]{5,}", term):
            expanded.extend(term[index : index + 3] for index in range(0, len(term) - 2, 2))
    return list(dict.fromkeys(expanded))[:12]


def _lexical_candidates(course_id: str, query: str, limit: int = 30) -> list[sqlite3.Row]:
    terms = _query_terms(query)
    with _database_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM material_chunks WHERE course_id = ?",
            (course_id,),
        ).fetchall()
    scored = []
    for row in rows:
        lowered = str(row["content"]).lower()
        score = sum((3 if term in lowered else 0) + lowered.count(term) for term in terms)
        if score:
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], int(item[1]["chunk_index"])))
    return [row for _, row in scored[:limit]]


def _keyword_candidates(course_id: str, query: str, limit: int = 30) -> list[sqlite3.Row]:
    terms = _query_terms(query)
    fts_rows: list[sqlite3.Row] = []
    if terms:
        match_query = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
        try:
            with _database_connection() as connection:
                fts_rows = connection.execute(
                    """
                    SELECT chunks.*
                    FROM material_chunks_fts
                    JOIN material_chunks AS chunks ON chunks.id = material_chunks_fts.chunk_id
                    WHERE material_chunks_fts MATCH ? AND material_chunks_fts.course_id = ?
                    ORDER BY bm25(material_chunks_fts)
                    LIMIT ?
                    """,
                    (match_query, course_id, limit),
                ).fetchall()
        except sqlite3.OperationalError:
            fts_rows = []

    seen = {str(row["id"]) for row in fts_rows}
    combined = list(fts_rows)
    for row in _lexical_candidates(course_id, query, limit=limit):
        if str(row["id"]) in seen:
            continue
        combined.append(row)
        seen.add(str(row["id"]))
        if len(combined) >= limit:
            break
    return combined


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return -1.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return -1.0
    return numerator / (left_norm * right_norm)


_VECTOR_MATRIX_TTL = 300.0
_VECTOR_MATRIX_CACHE: dict[str, "_VectorMatrix"] = {}
_VECTOR_CACHE_LOCK = threading.Lock()


@dataclass
class _VectorMatrix:
    """已 L2 归一化的向量矩阵缓存，余弦相似度退化为点积。"""

    chunk_ids: list[str]
    chunk_id_to_index: dict[str, int]
    matrix: Any  # numpy.ndarray, shape (N, D)
    loaded_at: float


def _invalidate_vector_cache(model: str | None = None) -> None:
    """写入 chunk_embeddings 后调用，保证下次检索读到最新向量。"""
    with _VECTOR_CACHE_LOCK:
        if model is None:
            _VECTOR_MATRIX_CACHE.clear()
        else:
            _VECTOR_MATRIX_CACHE.pop(model, None)


def _build_vector_matrix(model: str) -> _VectorMatrix | None:
    if np is None:
        return None
    with _embedding_connection() as connection:
        rows = connection.execute(
            "SELECT chunk_id, vector_json FROM chunk_embeddings WHERE model = ?",
            (model,),
        ).fetchall()
    chunk_ids: list[str] = []
    vectors: list[list[float]] = []
    for row in rows:
        try:
            vector = json.loads(row["vector_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(vector, list) or not vector:
            continue
        chunk_ids.append(str(row["chunk_id"]))
        vectors.append([float(value) for value in vector])
    if not chunk_ids:
        return None
    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    matrix = matrix / norms  # L2 归一化后余弦相似度 == 点积，避免每次检索重复归一化
    chunk_id_to_index = {chunk_id: index for index, chunk_id in enumerate(chunk_ids)}
    return _VectorMatrix(
        chunk_ids=chunk_ids,
        chunk_id_to_index=chunk_id_to_index,
        matrix=matrix,
        loaded_at=time.monotonic(),
    )


def _get_vector_matrix(model: str) -> _VectorMatrix | None:
    """获取该模型的向量矩阵，命中缓存直接返回；miss 时加锁构建。"""
    cached = _VECTOR_MATRIX_CACHE.get(model)
    if cached is not None and time.monotonic() - cached.loaded_at < _VECTOR_MATRIX_TTL:
        return cached
    with _VECTOR_CACHE_LOCK:
        cached = _VECTOR_MATRIX_CACHE.get(model)
        if cached is not None and time.monotonic() - cached.loaded_at < _VECTOR_MATRIX_TTL:
            return cached
        matrix = _build_vector_matrix(model)
        if matrix is not None:
            _VECTOR_MATRIX_CACHE[model] = matrix
        else:
            _VECTOR_MATRIX_CACHE.pop(model, None)
        return matrix


def _score_semantic_vectors(
    model: str,
    query_vector: list[float],
    course_ids: set[str],
) -> list[tuple[float, str]]:
    """对课程范围内的 chunk 计算余弦相似度，返回 (score, chunk_id) 未排序列表。

    优先走 numpy 向量化 + 进程内矩阵缓存（O(M·D)，M 为课程 chunk 数）；
    numpy 不可用时回退到逐条 Python 计算。原实现每次检索都把全表向量
    json.loads 进内存逐条算余弦，资料变多后是明显瓶颈。
    """
    vector_matrix = _get_vector_matrix(model)
    if vector_matrix is not None and np is not None and query_vector:
        mapping = vector_matrix.chunk_id_to_index
        indices = [mapping[cid] for cid in course_ids if cid in mapping]
        if not indices:
            return []
        query = np.asarray(query_vector, dtype=np.float32)
        query_norm = np.linalg.norm(query)
        if query_norm > 0:
            query = query / query_norm
        # 只取课程子集做矩阵向量乘，避免对其他课程做无效计算
        scores = vector_matrix.matrix[indices] @ query
        chunk_ids = vector_matrix.chunk_ids
        return [
            (float(scores[position]), chunk_ids[indices[position]])
            for position in range(len(indices))
        ]

    course_id_set = course_ids
    with _embedding_connection() as connection:
        vector_rows = connection.execute(
            "SELECT chunk_id, vector_json FROM chunk_embeddings WHERE model = ?",
            (model,),
        ).fetchall()
    scored: list[tuple[float, str]] = []
    for vector_row in vector_rows:
        chunk_id = str(vector_row["chunk_id"])
        if chunk_id not in course_id_set:
            continue
        vector = json.loads(vector_row["vector_json"])
        scored.append((_cosine_similarity(query_vector, vector), chunk_id))
    return scored


def sample_material_chunks(course_id: str, *, max_characters: int = 15000) -> str:
    """广覆盖采样课程资料文本，供 Glossary Scanner 提取术语使用。

    与 retrieve_material_context 的相关度 top-K 不同：术语提取要的是「见多识广」，
    因此按 (relative_path, chunk_index) 顺序遍历，每份材料均匀抽取片段，拼成
    `[来源：文件名 · 定位符]` 前缀的纯文本。
    """
    initialize_knowledge_database()
    with _database_connection() as connection:
        rows = connection.execute(
            "SELECT material_name, locator, content FROM material_chunks "
            "WHERE course_id = ? ORDER BY relative_path, chunk_index",
            (course_id,),
        ).fetchall()
    if not rows:
        return ""
    per_material = max(1, max_characters // max(1, len({str(row["material_name"]) for row in rows})))
    seen_counts: dict[str, int] = {}
    pieces: list[str] = []
    total = 0
    for row in rows:
        name = str(row["material_name"])
        if seen_counts.get(name, 0) >= per_material:
            continue
        piece = str(row["content"]).strip()
        if not piece:
            continue
        seen_counts[name] = seen_counts.get(name, 0) + 1
        prefix = f"[来源：{name} · {row['locator']}]"
        segment = f"{prefix}\n{piece}"
        if total + len(segment) > max_characters:
            break
        pieces.append(segment)
        total += len(segment)
    return "\n\n".join(pieces)


def retrieve_material_context(course_id: str, query: str, *, limit: int = 6) -> dict[str, Any]:
    global _EMBEDDING_UNAVAILABLE_UNTIL
    initialize_knowledge_database()
    lexical_rows = _keyword_candidates(course_id, query)
    ranks: dict[str, float] = {
        str(row["id"]): 1 / (60 + rank)
        for rank, row in enumerate(lexical_rows, start=1)
    }
    row_by_id = {str(row["id"]): row for row in lexical_rows}

    config = _read_embedding_config()
    semantic_used = False
    if config.get("enabled") and time.monotonic() >= _EMBEDDING_UNAVAILABLE_UNTIL:
        try:
            query_vector = _request_embeddings([query])[0]
            with _database_connection() as connection:
                course_rows = connection.execute(
                    "SELECT * FROM material_chunks WHERE course_id = ?",
                    (course_id,),
                ).fetchall()
            course_ids = {str(row["id"]) for row in course_rows}
            row_by_id.update({str(row["id"]): row for row in course_rows})
            scored_vectors = _score_semantic_vectors(
                str(config["model"]), query_vector, course_ids
            )
            scored_vectors.sort(reverse=True)
            for rank, (_, chunk_id) in enumerate(scored_vectors[:30], start=1):
                ranks[chunk_id] = ranks.get(chunk_id, 0) + 1 / (60 + rank)
            semantic_used = bool(scored_vectors)
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError, json.JSONDecodeError):
            semantic_used = False
            _EMBEDDING_UNAVAILABLE_UNTIL = time.monotonic() + 30

    ranked_ids = sorted(ranks, key=lambda chunk_id: ranks[chunk_id], reverse=True)[:limit]
    items = []
    for chunk_id in ranked_ids:
        row = row_by_id[chunk_id]
        citation = f"{row['material_name']} · {row['locator']}"
        items.append(
            {
                "chunkId": chunk_id,
                "source": str(row["relative_path"]),
                "locator": str(row["locator"]),
                "citation": citation,
                "content": str(row["content"]),
            }
        )
    context = "\n\n".join(
        f"[来源：{item['citation']}]\n{item['content']}" for item in items
    )
    return {"items": items, "context": context, "semanticUsed": semantic_used}


def record_chat_turn(
    course_id: str,
    role: str,
    content: str,
    *,
    mode: str = "chat",
    external_id: str = "",
    sources: list[dict[str, Any]] | None = None,
    created_at: str | None = None,
) -> None:
    initialize_knowledge_database()
    conversation_mode = "agent" if mode == "agent" else "chat"
    with _database_connection() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO chat_turns (
                external_id, course_id, role, conversation_mode, content, sources_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                external_id or None,
                course_id,
                role,
                conversation_mode,
                content,
                json.dumps(sources or [], ensure_ascii=False),
                created_at or _now(),
            ),
        )


def import_workspace_messages(course_id: str, messages: list[dict[str, Any]]) -> None:
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in ("user", "assistant"):
            continue
        content = str(message.get("content", "")).strip()
        if content:
            record_chat_turn(
                course_id,
                str(message["role"]),
                content,
                mode=str(message.get("mode") or "chat"),
                external_id=str(message.get("id", "")),
                created_at=str(message.get("createdAt") or _now()),
            )


def recent_chat_messages(course_id: str, *, mode: str = "chat", limit: int = 8) -> list[dict[str, str]]:
    initialize_knowledge_database()
    conversation_mode = "agent" if mode == "agent" else "chat"
    with _database_connection() as connection:
        rows = connection.execute(
            """
            SELECT role, content
            FROM chat_turns
            WHERE course_id = ? AND conversation_mode = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (course_id, conversation_mode, limit),
        ).fetchall()
    return [{"role": str(row["role"]), "content": str(row["content"])} for row in reversed(rows)]


def latest_summarized_turn_id(course_id: str, *, mode: str = "chat") -> int:
    """已压缩区间的最大 chat_turns.id；尚无摘要时返回 0。"""
    initialize_knowledge_database()
    conversation_mode = "agent" if mode == "agent" else "chat"
    with _database_connection() as connection:
        row = connection.execute(
            "SELECT MAX(to_turn_id) AS latest FROM chat_summaries WHERE course_id = ? AND conversation_mode = ?",
            (course_id, conversation_mode),
        ).fetchone()
    return int(row["latest"] or 0)


def unsummarized_chat_turns(
    course_id: str, *, mode: str = "chat", after_turn_id: int = 0
) -> list[dict[str, Any]]:
    """返回 id > after_turn_id 的全部对话原文（id 升序），供滚动摘要压缩。"""
    initialize_knowledge_database()
    conversation_mode = "agent" if mode == "agent" else "chat"
    with _database_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, role, content
            FROM chat_turns
            WHERE course_id = ? AND conversation_mode = ? AND id > ?
            ORDER BY id ASC
            """,
            (course_id, conversation_mode, after_turn_id),
        ).fetchall()
    return [
        {"id": int(row["id"]), "role": str(row["role"]), "content": str(row["content"])}
        for row in rows
    ]


def record_chat_summary(
    course_id: str,
    content: str,
    from_turn_id: int,
    to_turn_id: int,
    *,
    mode: str = "chat",
) -> None:
    """持久化一段对话脉络摘要，并记录其覆盖的原始 turn id 区间。"""
    initialize_knowledge_database()
    conversation_mode = "agent" if mode == "agent" else "chat"
    with _database_connection() as connection:
        connection.execute(
            """
            INSERT INTO chat_summaries (
                course_id, conversation_mode, content, from_turn_id, to_turn_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (course_id, conversation_mode, content, from_turn_id, to_turn_id, _now()),
        )


def get_rolling_summaries(course_id: str, *, mode: str = "chat") -> list[str]:
    """返回全部已存脉络摘要（时间升序），用于拼成早期对话背景。"""
    initialize_knowledge_database()
    conversation_mode = "agent" if mode == "agent" else "chat"
    with _database_connection() as connection:
        rows = connection.execute(
            """
            SELECT content
            FROM chat_summaries
            WHERE course_id = ? AND conversation_mode = ?
            ORDER BY id ASC
            """,
            (course_id, conversation_mode),
        ).fetchall()
    return [str(row["content"]) for row in rows]


def related_chat_history(
    course_id: str,
    query: str,
    *,
    mode: str = "chat",
    limit: int = 4,
    exclude_recent: int = 8,
) -> list[dict[str, str]]:
    """按当前 query 的词法相关性，从早期历史（排除近期窗口）捞回最相关的片段。

    近期窗口原文已由 recent_chat_messages 提供，这里刻意排除最近 exclude_recent 条，
    避免重复，确保捞回的是更早的对话脉络。最终按 id 升序输出以保持时序。
    """
    initialize_knowledge_database()
    conversation_mode = "agent" if mode == "agent" else "chat"
    terms = _query_terms(query)
    with _database_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, role, content
            FROM chat_turns
            WHERE course_id = ? AND conversation_mode = ?
            ORDER BY id DESC
            """,
            (course_id, conversation_mode),
        ).fetchall()
    candidates = rows[exclude_recent:]
    if not candidates or not terms:
        return []
    scored: list[tuple[float, int, sqlite3.Row]] = []
    for row in candidates:
        lowered = str(row["content"]).lower()
        score = sum((3 if term in lowered else 0) + lowered.count(term) for term in terms)
        if score:
            scored.append((score, int(row["id"]), row))
    scored.sort(key=lambda item: (-item[0], item[1]))
    picked = sorted(scored[:limit], key=lambda item: item[1])
    return [
        {"role": str(row["role"]), "content": str(row["content"])}
        for _, _, row in picked
    ]


def build_conversation_memory(
    course_id: str, query: str, *, mode: str = "chat"
) -> dict[str, Any]:
    """分层对话记忆：近期原文窗口 + 早期滚动摘要 + 相关性检索片段。

    - recent：最近 8 条原文，保证多轮工具调用的逐字连贯。
    - summary_text：已被压缩的早期对话脉络（多段摘要拼接），可能为空。
    - related_text：与当前 query 相关的早期原文片段，可能为空。
    """
    recent = recent_chat_messages(course_id, mode=mode, limit=8)
    summaries = get_rolling_summaries(course_id, mode=mode)
    summary_text = "\n".join(f"- {item}" for item in summaries).strip() if summaries else ""
    related = related_chat_history(course_id, query, mode=mode, limit=4, exclude_recent=8)
    related_text = (
        "\n".join(
            f"{'用户' if item['role'] == 'user' else 'AI'}：{item['content']}"
            for item in related
        ).strip()
        if related
        else ""
    )
    return {"recent": recent, "summary_text": summary_text, "related_text": related_text}


def upsert_learner_memory(
    course_id: str,
    memory_type: str,
    content: str,
    *,
    knowledge_point_id: str = "",
    confidence: float = 0.7,
    source_type: str,
    evidence_id: str,
) -> str:
    normalized = re.sub(r"\s+", " ", content).strip()
    memory_id = hashlib.sha256(
        f"{course_id}|{memory_type}|{knowledge_point_id}|{normalized}".encode("utf-8")
    ).hexdigest()[:32]
    timestamp = _now()
    with _database_connection() as connection:
        connection.execute(
            """
            INSERT INTO learner_memories (
                id, course_id, memory_type, knowledge_point_id, content,
                confidence, status, source_type, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                confidence = MAX(learner_memories.confidence, excluded.confidence),
                status = 'active',
                updated_at = excluded.updated_at
            """,
            (
                memory_id,
                course_id,
                memory_type,
                knowledge_point_id,
                normalized,
                max(0.0, min(1.0, float(confidence))),
                source_type,
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            "INSERT OR IGNORE INTO memory_evidence (memory_id, evidence_type, evidence_id, created_at) VALUES (?, ?, ?, ?)",
            (memory_id, source_type, evidence_id, timestamp),
        )
    # best-effort 为该条记忆计算并持久化向量；embedding 关闭或不可用时静默跳过，不影响记忆写入。
    _ensure_memory_embedding(memory_id, normalized)
    return memory_id


def record_learning_event(
    course_id: str,
    event_type: str,
    *,
    knowledge_point_id: str = "",
    question_id: str = "",
    is_correct: bool | None = None,
    details: dict[str, Any] | None = None,
) -> str:
    timestamp = _now()
    payload = details or {}
    raw_id = f"{course_id}|{event_type}|{question_id}|{timestamp}|{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
    event_id = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:32]
    with _database_connection() as connection:
        connection.execute(
            """
            INSERT INTO learning_events (
                id, course_id, event_type, knowledge_point_id, question_id,
                is_correct, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                course_id,
                event_type,
                knowledge_point_id,
                question_id,
                None if is_correct is None else int(is_correct),
                json.dumps(payload, ensure_ascii=False),
                timestamp,
            ),
        )
    if is_correct is False:
        title = str(payload.get("title") or question_id or "一道题")
        upsert_learner_memory(
            course_id,
            "weak_point",
            f"用户在{event_type}中答错「{title}」，需要继续巩固。",
            knowledge_point_id=knowledge_point_id,
            confidence=0.85,
            source_type="learning_event",
            evidence_id=event_id,
        )
    return event_id


def _load_memory_vectors(memory_ids: list[str], model: str) -> dict[str, list[float]]:
    """批量读取记忆向量。memory_ids 来自主库、向量在 embedding 库，跨库不能 JOIN，故分两步查。"""
    if not memory_ids:
        return {}
    placeholders = ",".join("?" for _ in memory_ids)
    with _embedding_connection() as connection:
        rows = connection.execute(
            f"SELECT memory_id, vector_json FROM memory_embeddings WHERE model = ? AND memory_id IN ({placeholders})",
            (model, *memory_ids),
        ).fetchall()
    vectors: dict[str, list[float]] = {}
    for row in rows:
        try:
            vectors[str(row["memory_id"])] = json.loads(row["vector_json"])
        except (TypeError, json.JSONDecodeError):
            continue
    return vectors


def _ensure_memory_embedding(memory_id: str, content: str) -> None:
    """best-effort 为单条记忆计算并持久化向量。

    embedding 关闭、熔断期或服务异常时静默跳过——记忆本体已写入，向量缺失只会让检索
    回退到词法打分（learner_memory_context 对缺失向量自然降级），不影响功能。
    """
    config = _read_embedding_config()
    if not config.get("enabled"):
        return
    if time.monotonic() < _EMBEDDING_UNAVAILABLE_UNTIL:
        return  # 检索路径已探明不可用，写入路径不再重试，避免每次 upsert 都探测
    model = str(config["model"])
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    with _embedding_connection() as connection:
        cached = connection.execute(
            "SELECT content_hash FROM memory_embeddings WHERE memory_id = ? AND model = ?",
            (memory_id, model),
        ).fetchone()
        if cached and cached["content_hash"] == content_hash:
            return  # 内容未变，复用已有向量，避免重复 embed
    try:
        vector = _request_embeddings([content])[0]
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError, json.JSONDecodeError):
        return
    with _embedding_connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO memory_embeddings (
                memory_id, model, content_hash, dimension, vector_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                model,
                content_hash,
                len(vector),
                json.dumps(vector, separators=(",", ":")),
                _now(),
            ),
        )


def learner_memory_context(course_id: str, query: str, *, limit: int = 5) -> str:
    """检索长期记忆：词法 + 置信度 + 时近 基础分，embedding 启用时叠加语义相似度。

    与资料检索 retrieve_material_context 架构一致（混合打分 + 熔断）；embedding 关闭或不可用时
    优雅回退到纯词法打分（旧行为），避免记忆累积后同义不同词的表述无法被召回、质量下滑。
    """
    global _EMBEDDING_UNAVAILABLE_UNTIL
    terms = _query_terms(query)
    with _database_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM learner_memories
            WHERE course_id = ? AND status = 'active'
            ORDER BY updated_at DESC LIMIT 80
            """,
            (course_id,),
        ).fetchall()
    if not rows:
        return ""

    # 基础分（旧行为）：词法命中 *10 + 置信度 + 时近。保证无 embedding 时仍可召回。
    scores: dict[str, float] = {}
    content_by_id: dict[str, str] = {}
    for recency, row in enumerate(rows):
        memory_id = str(row["id"])
        lowered = str(row["content"]).lower()
        content_by_id[memory_id] = str(row["content"])
        lexical = sum(lowered.count(term) for term in terms)
        scores[memory_id] = lexical * 10 + float(row["confidence"]) + 1 / (recency + 1)

    # 语义增强：覆盖词法盲区（同义不同词）。缺失向量的记忆自然跳过，不影响其基础分。
    config = _read_embedding_config()
    if config.get("enabled") and time.monotonic() >= _EMBEDDING_UNAVAILABLE_UNTIL:
        try:
            query_vector = _request_embeddings([query])[0]
            vectors = _load_memory_vectors(list(content_by_id), str(config["model"]))
            if vectors:
                semantic_ranked = sorted(
                    ((_cosine_similarity(query_vector, vec), mid) for mid, vec in vectors.items()),
                    reverse=True,
                )
                for similarity, memory_id in semantic_ranked:
                    # sim∈[-1,1] 截断到 [0,1] 后乘 10，与单个词法命中量级相当：
                    # 既能召回同义记忆，又不会淹没词法强命中与置信度。
                    scores[memory_id] = scores.get(memory_id, 0.0) + max(0.0, similarity) * 10
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError, json.JSONDecodeError):
            _EMBEDDING_UNAVAILABLE_UNTIL = time.monotonic() + 30

    ranked_ids = sorted(content_by_id, key=lambda mid: scores[mid], reverse=True)[:limit]
    return "\n".join(f"- {content_by_id[mid]}" for mid in ranked_ids)


def record_review_progress(
    course_id: str,
    previous_tasks: list[dict[str, Any]],
    current_tasks: list[dict[str, Any]],
) -> None:
    previous_by_id = {str(task.get("id")): task for task in previous_tasks if isinstance(task, dict)}
    default_titles = ["考点与边界", "概念与方法", "例题与迁移", "自测与纠错"]
    with _database_connection() as connection:
        for task in current_tasks:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("id", ""))
            old_progress = int(previous_by_id.get(task_id, {}).get("progress", 0))
            new_progress = int(task.get("progress", 0))
            if new_progress <= old_progress:
                continue
            guide = task.get("studyGuide") if isinstance(task.get("studyGuide"), dict) else {}
            sections = guide.get("sections") if isinstance(guide.get("sections"), list) else []
            for section_index in range(1, 5):
                threshold = section_index * 25
                if not (old_progress < threshold <= new_progress):
                    continue
                section = sections[section_index - 1] if len(sections) >= section_index else {}
                title = str(section.get("title") or default_titles[section_index - 1])
                content = json.dumps(section, ensure_ascii=False, sort_keys=True) if section else title
                connection.execute(
                    """
                    INSERT OR REPLACE INTO review_sections (
                        course_id, task_id, section_index, section_key,
                        title, content_hash, completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        course_id,
                        task_id,
                        section_index,
                        str(section.get("id") or f"section-{section_index}"),
                        title,
                        _content_hash(content),
                        _now(),
                    ),
                )


def get_knowledge_status(course_id: str) -> dict[str, Any]:
    initialize_knowledge_database()
    with _database_connection() as connection:
        materials = int(
            connection.execute(
                "SELECT COUNT(*) FROM knowledge_materials WHERE course_id = ?",
                (course_id,),
            ).fetchone()[0]
        )
        chunks = int(
            connection.execute(
                "SELECT COUNT(*) FROM material_chunks WHERE course_id = ?",
                (course_id,),
            ).fetchone()[0]
        )
        chats = int(
            connection.execute(
                "SELECT COUNT(*) FROM chat_turns WHERE course_id = ?",
                (course_id,),
            ).fetchone()[0]
        )
        events = int(
            connection.execute(
                "SELECT COUNT(*) FROM learning_events WHERE course_id = ?",
                (course_id,),
            ).fetchone()[0]
        )
        memories = int(
            connection.execute(
                "SELECT COUNT(*) FROM learner_memories WHERE course_id = ? AND status = 'active'",
                (course_id,),
            ).fetchone()[0]
        )
    return {
        "courseId": course_id,
        "materials": materials,
        "chunks": chunks,
        "chatTurns": chats,
        "learningEvents": events,
        "memories": memories,
        "embedding": get_embedding_status(probe=False),
    }
