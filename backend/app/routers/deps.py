"""跨 router 共享的底层依赖：SQLite 连接、归档表辅助、当前用户（owner）。

路由模块只从这里 import，main.py 也从这里取 get_connection，
保持 main → routers 单向依赖，避免循环导入。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel

DATA_DIRECTORY = Path(__file__).resolve().parent.parent.parent / "data"
DATABASE_PATH = DATA_DIRECTORY / "exam_booster.db"
ARCHIVE_RETENTION_DAYS = 7


def get_connection() -> sqlite3.Connection:
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    # timeout=30：多用户并发写下等待锁而非立刻报 database is locked
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def current_owner_id(request: Request) -> str:
    """从 AuthMiddleware 注入的 request.state 取当前用户 id（阶段2 owner 过滤的统一入口）。

    白名单路径（auth/health）不会走到这里；中间件已保证非白名单 /api/* 请求
    必然携带 user_id，此处的 401 只是防御性兜底。
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    return str(user_id)


def course_is_owned(connection: sqlite3.Connection, course_id: str, owner_id: str) -> bool:
    """课程存在且属于该 owner。路由层用它做归属校验（不通过 → 404）。"""
    row = connection.execute(
        "SELECT 1 FROM courses WHERE id = ? AND owner_id = ?",
        (course_id, owner_id),
    ).fetchone()
    return row is not None


def require_course_ownership(course_id: str, owner_id: str = Depends(current_owner_id)) -> str:
    """课程归属依赖：校验 course_id 属于当前用户，返回 owner_id（供 INSERT/归档使用）。

    归属不通过统一 404（不泄露课程是否存在）；课程不存在同样 404。
    """
    with get_connection() as connection:
        if not course_is_owned(connection, course_id, owner_id):
            raise HTTPException(status_code=404, detail="课程不存在")
    return owner_id


class ArchiveItemResponse(BaseModel):
    id: str
    item_type: Literal["course", "wrong-answer"]
    entity_id: str
    title: str
    course_id: str | None = None
    course_name: str | None = None
    deleted_at: str
    purge_after: str


class WrongAnswerArchiveResponse(BaseModel):
    workspace: dict[str, Any]
    archive_item: ArchiveItemResponse


def row_to_archive_item(row: sqlite3.Row) -> ArchiveItemResponse:
    return ArchiveItemResponse(
        id=row["id"],
        item_type=row["item_type"],
        entity_id=row["entity_id"],
        title=row["title"],
        course_id=row["course_id"],
        course_name=row["course_name"],
        deleted_at=row["deleted_at"],
        purge_after=row["purge_after"],
    )


def _delete_material_caches(course_directory: Path) -> None:
    """删除课程资料生成的解析/预览缓存（缓存键包含文件绝对路径和 stat）。"""
    cache_directory = DATA_DIRECTORY / "material_cache"
    if not course_directory.exists() or not cache_directory.exists():
        return
    for file_path in course_directory.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            stat = file_path.stat()
            raw_key = f"{file_path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
            cache_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:24]
            for cache_path in cache_directory.glob(f"*-{cache_key}.*"):
                cache_path.unlink(missing_ok=True)
        except OSError:
            # 单个缓存或资料文件被占用时不阻断其余课程数据的清理。
            continue


def permanently_delete_course_data(connection: sqlite3.Connection, course_id: str) -> None:
    """彻底清理课程在 data 目录、主库及向量缓存库中的全部持久化数据。"""
    course_directory = DATA_DIRECTORY / "courses" / course_id
    _delete_material_caches(course_directory)

    existing_tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }

    def ids_for(table: str, id_column: str = "id") -> list[str]:
        if table not in existing_tables:
            return []
        return [
            str(row[0])
            for row in connection.execute(
                f"SELECT {id_column} FROM {table} WHERE course_id = ?", (course_id,)
            ).fetchall()
        ]

    chunk_ids = ids_for("material_chunks")
    memory_ids = ids_for("learner_memories")
    run_ids = ids_for("agent_runs")

    if chunk_ids:
        try:
            connection.executemany("DELETE FROM material_chunks_fts WHERE chunk_id = ?", [(item,) for item in chunk_ids])
        except sqlite3.OperationalError:
            pass
    if memory_ids and "memory_evidence" in existing_tables:
        connection.executemany("DELETE FROM memory_evidence WHERE memory_id = ?", [(item,) for item in memory_ids])
    if run_ids and "agent_steps" in existing_tables:
        connection.executemany("DELETE FROM agent_steps WHERE run_id = ?", [(item,) for item in run_ids])

    for table in (
        "plan_tasks",
        "agent_jobs",
        "artifacts",
        "adjustment_proposals",
        "external_sources",
        "glossary_terms",
        "glossary_refresh_state",
        "knowledge_materials",
        "material_chunks",
        "chat_turns",
        "learning_events",
        "review_sections",
        "chat_summaries",
        "learner_memories",
        "agent_runs",
    ):
        if table in existing_tables:
            connection.execute(f"DELETE FROM {table} WHERE course_id = ?", (course_id,))
    if "courses" in existing_tables:
        connection.execute("DELETE FROM courses WHERE id = ?", (course_id,))

    embedding_path = DATA_DIRECTORY / "embedding_cache.db"
    if embedding_path.exists() and (chunk_ids or memory_ids):
        with sqlite3.connect(embedding_path, timeout=30) as embedding_connection:
            if chunk_ids:
                embedding_connection.executemany(
                    "DELETE FROM chunk_embeddings WHERE chunk_id = ?", [(item,) for item in chunk_ids]
                )
            if memory_ids:
                embedding_connection.executemany(
                    "DELETE FROM memory_embeddings WHERE memory_id = ?", [(item,) for item in memory_ids]
                )

    if course_directory.exists():
        shutil.rmtree(course_directory)


def permanently_delete_archive_item(connection: sqlite3.Connection, archive_id: str, owner_id: str | None = None) -> bool:
    query = "SELECT id, item_type, entity_id, course_id FROM archived_items WHERE id = ?"
    parameters: tuple[str, ...] = (archive_id,)
    if owner_id is not None:
        query += " AND owner_id = ?"
        parameters = (archive_id, owner_id)
    row = connection.execute(query, parameters).fetchone()
    if row is None:
        return False
    if row["item_type"] == "course":
        permanently_delete_course_data(connection, str(row["course_id"] or row["entity_id"]))
    connection.execute("DELETE FROM archived_items WHERE id = ?", (archive_id,))
    return True


def purge_expired_archive_items(connection: sqlite3.Connection) -> int:
    rows = connection.execute(
        "SELECT id FROM archived_items WHERE purge_after <= ?",
        (datetime.now().isoformat(timespec="seconds"),),
    ).fetchall()
    for row in rows:
        permanently_delete_archive_item(connection, str(row["id"]))
    return len(rows)


def list_active_archive_items(
    connection: sqlite3.Connection,
    owner_id: str | None = None,
) -> list[ArchiveItemResponse]:
    """列出当前有效的归档项；owner_id 非空时只看该用户的（阶段2 多租户）。"""
    purge_expired_archive_items(connection)
    if owner_id is None:
        rows = connection.execute(
            """
            SELECT id, item_type, entity_id, title, course_id, course_name, deleted_at, purge_after
            FROM archived_items
            ORDER BY deleted_at DESC
            """
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT id, item_type, entity_id, title, course_id, course_name, deleted_at, purge_after
            FROM archived_items
            WHERE owner_id = ?
            ORDER BY deleted_at DESC
            """
            ,
            (owner_id,),
        ).fetchall()
    return [row_to_archive_item(row) for row in rows]


def create_archive_item(
    connection: sqlite3.Connection,
    *,
    item_type: Literal["course", "wrong-answer"],
    entity_id: str,
    title: str,
    payload: dict[str, Any],
    owner_id: str = "",
    course_id: str | None = None,
    course_name: str | None = None,
) -> ArchiveItemResponse:
    deleted_at = datetime.now().isoformat(timespec="seconds")
    archive_id = f"archive-{item_type}-{entity_id}-{int(datetime.now().timestamp() * 1000)}"
    purge_after = (datetime.fromisoformat(deleted_at) + timedelta(days=ARCHIVE_RETENTION_DAYS)).isoformat(
        timespec="seconds",
    )
    connection.execute(
        """
        INSERT INTO archived_items (
            id, owner_id, item_type, entity_id, title, course_id, course_name, payload, deleted_at, purge_after
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            archive_id,
            owner_id,
            item_type,
            entity_id,
            title,
            course_id,
            course_name,
            json.dumps(payload, ensure_ascii=False),
            deleted_at,
            purge_after,
        ),
    )
    return ArchiveItemResponse(
        id=archive_id,
        item_type=item_type,
        entity_id=entity_id,
        title=title,
        course_id=course_id,
        course_name=course_name,
        deleted_at=deleted_at,
        purge_after=purge_after,
    )
