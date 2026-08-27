from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable


DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "data"
DATABASE_PATH = DATA_DIRECTORY / "exam_booster.db"


class AgentJobCancelled(RuntimeError):
    """Raised cooperatively when a persisted background job is cancelled."""



def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_agent_database() -> None:
    with _connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL,
                workflow TEXT NOT NULL,
                status TEXT NOT NULL,
                input_json TEXT NOT NULL DEFAULT '{}',
                output_json TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_steps (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                agent_name TEXT NOT NULL,
                status TEXT NOT NULL,
                input_json TEXT NOT NULL DEFAULT '{}',
                output_json TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES agent_runs(id)
            );
            CREATE INDEX IF NOT EXISTS idx_agent_steps_run
                ON agent_steps (run_id, step_index);

            CREATE TABLE IF NOT EXISTS agent_jobs (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL,
                job_type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                available_at TEXT NOT NULL,
                lease_until TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                result_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_agent_jobs_ready
                ON agent_jobs (status, available_at, created_at);

            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                version INTEGER NOT NULL,
                status TEXT NOT NULL,
                content_json TEXT NOT NULL,
                source_run_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE (course_id, artifact_type, version)
            );
            CREATE INDEX IF NOT EXISTS idx_artifacts_latest
                ON artifacts (course_id, artifact_type, version DESC);

            CREATE TABLE IF NOT EXISTS adjustment_proposals (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL,
                status TEXT NOT NULL,
                base_revision INTEGER NOT NULL,
                title TEXT NOT NULL,
                reason TEXT NOT NULL,
                impact TEXT NOT NULL,
                operations_json TEXT NOT NULL,
                before_json TEXT NOT NULL,
                after_json TEXT NOT NULL,
                source_run_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT '',
                dismissed_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_adjustment_proposals_course
                ON adjustment_proposals (course_id, status, created_at DESC);

            CREATE TABLE IF NOT EXISTS external_sources (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL,
                url TEXT NOT NULL,
                source_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS mcp_servers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                transport TEXT NOT NULL DEFAULT 'http',
                command TEXT NOT NULL DEFAULT '',
                args_json TEXT NOT NULL DEFAULT '[]',
                tools_json TEXT NOT NULL DEFAULT '[]',
                enabled INTEGER NOT NULL DEFAULT 1,
                allowed_tools_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS glossary_terms (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL,
                term TEXT NOT NULL,
                match_key TEXT NOT NULL,
                aliases_json TEXT NOT NULL DEFAULT '[]',
                one_liner TEXT NOT NULL DEFAULT '',
                article TEXT NOT NULL DEFAULT '',
                exam_tips_json TEXT NOT NULL DEFAULT '[]',
                pitfalls_json TEXT NOT NULL DEFAULT '[]',
                knowledge_point_id TEXT NOT NULL DEFAULT '',
                related_knowledge_point_ids_json TEXT NOT NULL DEFAULT '[]',
                module_id TEXT NOT NULL DEFAULT '',
                importance TEXT NOT NULL DEFAULT 'core',
                status TEXT NOT NULL DEFAULT 'active',
                origin TEXT NOT NULL DEFAULT 'curator',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (course_id, match_key)
            );
            CREATE INDEX IF NOT EXISTS idx_glossary_terms_course
                ON glossary_terms (course_id, status, importance);

            CREATE TABLE IF NOT EXISTS glossary_refresh_state (
                course_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'idle',
                content_signature TEXT NOT NULL DEFAULT '',
                terms_total INTEGER NOT NULL DEFAULT 0,
                terms_active INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                last_refreshed_at TEXT NOT NULL DEFAULT '',
                phase TEXT NOT NULL DEFAULT 'idle',
                candidates_total INTEGER NOT NULL DEFAULT 0,
                terms_completed INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL DEFAULT '',
                progress_updated_at TEXT NOT NULL DEFAULT ''
            );
            """
        )
        glossary_state_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(glossary_refresh_state)").fetchall()
        }
        for column, definition in {
            "phase": "TEXT NOT NULL DEFAULT 'idle'",
            "candidates_total": "INTEGER NOT NULL DEFAULT 0",
            "terms_completed": "INTEGER NOT NULL DEFAULT 0",
            "started_at": "TEXT NOT NULL DEFAULT ''",
            "progress_updated_at": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column not in glossary_state_columns:
                connection.execute(f"ALTER TABLE glossary_refresh_state ADD COLUMN {column} {definition}")

        existing_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(mcp_servers)").fetchall()
        }
        for column, definition in {
            "transport": "TEXT NOT NULL DEFAULT 'http'",
            "command": "TEXT NOT NULL DEFAULT ''",
            "args_json": "TEXT NOT NULL DEFAULT '[]'",
            "tools_json": "TEXT NOT NULL DEFAULT '[]'",
        }.items():
            if column not in existing_columns:
                connection.execute(f"ALTER TABLE mcp_servers ADD COLUMN {column} {definition}")

        # adjustment_proposals 表：为「按新参数重新编排」类提案追加 params_json 列，
        # 用于在用户「采纳」时一并落地 examDate/days/dailyHours（「忽略」则参数不落地，保持一致）。
        existing_proposal_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(adjustment_proposals)").fetchall()
        }
        if "params_json" not in existing_proposal_columns:
            connection.execute(
                "ALTER TABLE adjustment_proposals ADD COLUMN params_json TEXT NOT NULL DEFAULT '{}'"
            )


def create_agent_run(course_id: str, workflow: str, input_data: dict[str, Any] | None = None) -> str:
    initialize_agent_database()
    run_id = f"run-{uuid.uuid4().hex}"
    timestamp = _now()
    with _connection() as connection:
        connection.execute(
            "INSERT INTO agent_runs (id, course_id, workflow, status, input_json, created_at, updated_at) VALUES (?, ?, ?, 'running', ?, ?, ?)",
            (run_id, course_id, workflow, json.dumps(input_data or {}, ensure_ascii=False), timestamp, timestamp),
        )
    return run_id


def finish_agent_run(run_id: str, output: dict[str, Any] | None = None) -> None:
    with _connection() as connection:
        connection.execute(
            "UPDATE agent_runs SET status = 'completed', output_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(output or {}, ensure_ascii=False), _now(), run_id),
        )


def fail_agent_run(run_id: str, error: Exception | str) -> None:
    with _connection() as connection:
        connection.execute(
            "UPDATE agent_runs SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
            (str(error), _now(), run_id),
        )


def get_agent_run(run_id: str) -> dict[str, Any]:
    initialize_agent_database()
    with _connection() as connection:
        row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        steps = connection.execute(
            "SELECT * FROM agent_steps WHERE run_id = ? ORDER BY step_index, created_at",
            (run_id,),
        ).fetchall()
    if row is None:
        raise KeyError("Agent 运行记录不存在")
    return {
        "id": str(row["id"]),
        "courseId": str(row["course_id"]),
        "workflow": str(row["workflow"]),
        "status": str(row["status"]),
        "input": json.loads(row["input_json"]),
        "output": json.loads(row["output_json"]),
        "error": str(row["error"]),
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
        "steps": [
            {
                "id": str(step["id"]),
                "index": int(step["step_index"]),
                "agent": str(step["agent_name"]),
                "status": str(step["status"]),
                "input": json.loads(step["input_json"]),
                "output": json.loads(step["output_json"]),
                "error": str(step["error"]),
            }
            for step in steps
        ],
    }


def record_agent_step(
    run_id: str,
    step_index: int,
    agent_name: str,
    status: str,
    *,
    input_data: dict[str, Any] | None = None,
    output_data: dict[str, Any] | None = None,
    error: Exception | str = "",
) -> str:
    step_id = f"step-{uuid.uuid4().hex}"
    timestamp = _now()
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO agent_steps (
                id, run_id, step_index, agent_name, status, input_json,
                output_json, error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                step_id,
                run_id,
                step_index,
                agent_name,
                status,
                json.dumps(input_data or {}, ensure_ascii=False),
                json.dumps(output_data or {}, ensure_ascii=False),
                str(error),
                timestamp,
                timestamp,
            ),
        )
    return step_id


def save_artifact(
    course_id: str,
    artifact_type: str,
    content: dict[str, Any],
    *,
    status: str = "draft",
    source_run_id: str = "",
) -> dict[str, Any]:
    initialize_agent_database()
    artifact_id = f"artifact-{uuid.uuid4().hex}"
    with _connection() as connection:
        row = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM artifacts WHERE course_id = ? AND artifact_type = ?",
            (course_id, artifact_type),
        ).fetchone()
        version = int(row[0]) + 1
        connection.execute(
            "INSERT INTO artifacts (id, course_id, artifact_type, version, status, content_json, source_run_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                artifact_id,
                course_id,
                artifact_type,
                version,
                status,
                json.dumps(content, ensure_ascii=False),
                source_run_id,
                _now(),
            ),
        )
    return {"id": artifact_id, "type": artifact_type, "version": version, "status": status, "content": content}


def get_latest_artifact(course_id: str, artifact_type: str) -> dict[str, Any] | None:
    initialize_agent_database()
    with _connection() as connection:
        row = connection.execute(
            "SELECT * FROM artifacts WHERE course_id = ? AND artifact_type = ? ORDER BY version DESC LIMIT 1",
            (course_id, artifact_type),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "type": str(row["artifact_type"]),
        "version": int(row["version"]),
        "status": str(row["status"]),
        "content": json.loads(row["content_json"]),
        "sourceRunId": str(row["source_run_id"]),
    }


def enqueue_agent_job(
    course_id: str,
    job_type: str,
    payload: dict[str, Any],
    *,
    max_attempts: int = 3,
) -> str:
    initialize_agent_database()
    job_id = f"job-{uuid.uuid4().hex}"
    timestamp = _now()
    with _connection() as connection:
        # Idempotent queueing: workspace polling may request the same maintenance
        # job every 1.8 seconds. Reuse its active job instead of flooding FIFO.
        active = connection.execute(
            "SELECT id FROM agent_jobs WHERE course_id = ? AND job_type = ? "
            "AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1",
            (course_id, job_type),
        ).fetchone()
        if active is not None:
            return str(active["id"])
        connection.execute(
            """
            INSERT INTO agent_jobs (
                id, course_id, job_type, payload_json, status, attempts,
                max_attempts, available_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?)
            """,
            (job_id, course_id, job_type, json.dumps(payload, ensure_ascii=False), max_attempts, timestamp, timestamp, timestamp),
        )
    return job_id


def get_active_agent_job(course_id: str, job_type: str) -> dict[str, Any] | None:
    """Return the newest active job so a refreshed client can resume polling it."""
    initialize_agent_database()
    with _connection() as connection:
        row = connection.execute(
            "SELECT id FROM agent_jobs WHERE course_id = ? AND job_type = ? "
            "AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1",
            (course_id, job_type),
        ).fetchone()
    return get_agent_job(str(row["id"])) if row is not None else None


def cancel_agent_job(job_id: str) -> dict[str, Any]:
    """Cancel a queued/running job; workers observe this flag cooperatively."""
    initialize_agent_database()
    timestamp = _now()
    with _connection() as connection:
        row = connection.execute("SELECT status FROM agent_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError("Agent 后台任务不存在")
        if str(row["status"]) in {"queued", "running"}:
            connection.execute(
                "UPDATE agent_jobs SET status = 'cancelled', error = '', lease_until = '', updated_at = ? WHERE id = ?",
                (timestamp, job_id),
            )
    return get_agent_job(job_id)


def is_agent_job_cancelled(job_id: str) -> bool:
    initialize_agent_database()
    with _connection() as connection:
        row = connection.execute("SELECT status FROM agent_jobs WHERE id = ?", (job_id,)).fetchone()
    return row is not None and str(row["status"]) == "cancelled"


def delete_artifacts_for_run(run_id: str, artifact_types: list[str] | None = None) -> None:
    """Permanently remove transient/checkpoint content produced by one run."""
    if not run_id:
        return
    with _connection() as connection:
        if artifact_types:
            placeholders = ", ".join("?" for _ in artifact_types)
            connection.execute(
                f"DELETE FROM artifacts WHERE source_run_id = ? AND artifact_type IN ({placeholders})",
                (run_id, *artifact_types),
            )
        else:
            connection.execute("DELETE FROM artifacts WHERE source_run_id = ?", (run_id,))


def get_agent_job(job_id: str) -> dict[str, Any]:
    initialize_agent_database()
    with _connection() as connection:
        row = connection.execute("SELECT * FROM agent_jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise KeyError("Agent 后台任务不存在")
    return {
        "id": str(row["id"]),
        "courseId": str(row["course_id"]),
        "jobType": str(row["job_type"]),
        "status": str(row["status"]),
        "attempts": int(row["attempts"]),
        "maxAttempts": int(row["max_attempts"]),
        "error": str(row["error"]),
        "result": json.loads(row["result_json"]),
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
    }


def _claim_job() -> dict[str, Any] | None:
    initialize_agent_database()
    now = _now()
    lease_until = (datetime.now() + timedelta(minutes=10)).isoformat(timespec="seconds")
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE agent_jobs SET status = 'queued', lease_until = '' WHERE status = 'running' AND lease_until != '' AND lease_until < ?",
            (now,),
        )
        row = connection.execute(
            "SELECT * FROM agent_jobs WHERE status = 'queued' AND available_at <= ? "
            "ORDER BY CASE job_type "
            "WHEN 'approve_strategy_documents' THEN 0 "
            "WHEN 'external_source_import' THEN 1 "
            "WHEN 'orientation_refresh' THEN 2 "
            "WHEN 'glossary_refresh' THEN 3 "
            "WHEN 'maintain_review_plan' THEN 4 "
            "WHEN 'rebalance_daily_plan' THEN 5 ELSE 3 END, created_at LIMIT 1",
            (now,),
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        connection.execute(
            "UPDATE agent_jobs SET status = 'running', attempts = attempts + 1, lease_until = ?, updated_at = ? WHERE id = ?",
            (lease_until, now, row["id"]),
        )
        connection.commit()
    return {
        "id": str(row["id"]),
        "courseId": str(row["course_id"]),
        "jobType": str(row["job_type"]),
        "payload": json.loads(row["payload_json"]),
        "attempts": int(row["attempts"]) + 1,
        "maxAttempts": int(row["max_attempts"]),
    }


def _complete_job(job_id: str, result: dict[str, Any] | None = None) -> None:
    with _connection() as connection:
        connection.execute(
            "UPDATE agent_jobs SET status = 'completed', result_json = ?, lease_until = '', updated_at = ? "
            "WHERE id = ? AND status = 'running'",
            (json.dumps(result or {}, ensure_ascii=False), _now(), job_id),
        )


def _fail_job(job: dict[str, Any], error: Exception) -> None:
    if isinstance(error, AgentJobCancelled) or is_agent_job_cancelled(job["id"]):
        return
    exhausted = job["attempts"] >= job["maxAttempts"]
    status = "failed" if exhausted else "queued"
    delay_seconds = min(60, 2 ** job["attempts"])
    available_at = (datetime.now() + timedelta(seconds=delay_seconds)).isoformat(timespec="seconds")
    with _connection() as connection:
        connection.execute(
            "UPDATE agent_jobs SET status = ?, error = ?, available_at = ?, lease_until = '', updated_at = ? WHERE id = ?",
            (status, str(error), available_at, _now(), job["id"]),
        )


def _renew_job_lease(job_id: str) -> None:
    lease_until = (datetime.now() + timedelta(minutes=10)).isoformat(timespec="seconds")
    with _connection() as connection:
        connection.execute(
            "UPDATE agent_jobs SET lease_until = ?, updated_at = ? WHERE id = ? AND status = 'running'",
            (lease_until, _now(), job_id),
        )


def _lease_heartbeat(job_id: str, stop_event: threading.Event) -> None:
    while not stop_event.wait(60):
        _renew_job_lease(job_id)


class AgentJobWorker:
    def __init__(self, handlers: dict[str, Callable[[str, dict[str, Any]], dict[str, Any] | None]]) -> None:
        self._handlers = handlers
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="exam-booster-agent-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            job = _claim_job()
            if job is None:
                self._stop_event.wait(0.75)
                continue
            heartbeat_stop = threading.Event()
            heartbeat = threading.Thread(
                target=_lease_heartbeat, args=(job["id"], heartbeat_stop), daemon=True
            )
            heartbeat.start()
            try:
                handler = self._handlers.get(job["jobType"])
                if handler is None:
                    raise RuntimeError(f"未注册后台任务处理器：{job['jobType']}")
                payload = {**job["payload"], "_jobId": job["id"]}
                result = handler(job["courseId"], payload)
                _complete_job(job["id"], result)
            except Exception as error:
                _fail_job(job, error)
            finally:
                heartbeat_stop.set()
                heartbeat.join(timeout=1)


def create_adjustment_proposal(
    course_id: str,
    *,
    base_revision: int,
    title: str,
    reason: str,
    impact: str,
    operations: list[dict[str, Any]],
    before: dict[str, Any],
    after: dict[str, Any],
    source_run_id: str = "",
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initialize_agent_database()
    proposal_id = f"proposal-{uuid.uuid4().hex}"
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO adjustment_proposals (
                id, course_id, status, base_revision, title, reason, impact,
                operations_json, before_json, after_json, source_run_id, params_json, created_at
            ) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal_id,
                course_id,
                base_revision,
                title,
                reason,
                impact,
                json.dumps(operations, ensure_ascii=False),
                json.dumps(before, ensure_ascii=False),
                json.dumps(after, ensure_ascii=False),
                source_run_id,
                json.dumps(params or {}, ensure_ascii=False),
                _now(),
            ),
        )
    return get_adjustment_proposal(course_id, proposal_id)


def get_adjustment_proposal(course_id: str, proposal_id: str) -> dict[str, Any]:
    with _connection() as connection:
        row = connection.execute(
            "SELECT * FROM adjustment_proposals WHERE id = ? AND course_id = ?",
            (proposal_id, course_id),
        ).fetchone()
    if row is None:
        raise KeyError("调整提案不存在")
    return {
        "id": str(row["id"]),
        "courseId": str(row["course_id"]),
        "status": str(row["status"]),
        "baseRevision": int(row["base_revision"]),
        "title": str(row["title"]),
        "reason": str(row["reason"]),
        "impact": str(row["impact"]),
        "operations": json.loads(row["operations_json"]),
        "before": json.loads(row["before_json"]),
        "after": json.loads(row["after_json"]),
        "params": json.loads(row["params_json"] or "{}"),
    }


def list_pending_proposals(course_id: str) -> list[dict[str, Any]]:
    """列出某课程下所有 pending 状态的调整提案，按创建时间倒序。"""
    with _connection() as connection:
        rows = connection.execute(
            "SELECT * FROM adjustment_proposals WHERE course_id = ? AND status = 'pending' ORDER BY created_at DESC",
            (course_id,),
        ).fetchall()
    proposals: list[dict[str, Any]] = []
    for row in rows:
        proposals.append(
            {
                "id": str(row["id"]),
                "courseId": str(row["course_id"]),
                "status": str(row["status"]),
                "baseRevision": int(row["base_revision"]),
                "title": str(row["title"]),
                "reason": str(row["reason"]),
                "impact": str(row["impact"]),
                "operations": json.loads(row["operations_json"]),
                "before": json.loads(row["before_json"]),
                "after": json.loads(row["after_json"]),
                "params": json.loads(row["params_json"] or "{}"),
            }
        )
    return proposals


def set_proposal_status(course_id: str, proposal_id: str, status: str) -> None:
    if status not in {"applied", "dismissed"}:
        raise ValueError("提案状态无效")
    timestamp_column = "applied_at" if status == "applied" else "dismissed_at"
    with _connection() as connection:
        changed = connection.execute(
            f"UPDATE adjustment_proposals SET status = ?, {timestamp_column} = ? WHERE id = ? AND course_id = ? AND status = 'pending'",
            (status, _now(), proposal_id, course_id),
        ).rowcount
    if not changed:
        raise RuntimeError("提案已处理或不存在")


def last_proposal_resolution_at(course_id: str) -> str | None:
    """最近一次被「采纳 / 忽略」的提案时间戳。

    用于在用户刚处理完一条调整建议后，抑制「打开课程空间即自动再生成新提案」的循环——
    否则只要计划仍超额/逾期，每次加载空间都会再补一条建议，看起来就像卡片永远不消失。
    """
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT applied_at, dismissed_at
            FROM adjustment_proposals
            WHERE course_id = ? AND status IN ('applied', 'dismissed')
            ORDER BY COALESCE(applied_at, dismissed_at) DESC
            LIMIT 1
            """,
            (course_id,),
        ).fetchone()
    if not row:
        return None
    return row["applied_at"] or row["dismissed_at"]


def create_external_source(course_id: str, url: str, source_type: str = "web") -> dict[str, Any]:
    initialize_agent_database()
    source_id = f"source-{uuid.uuid4().hex}"
    timestamp = _now()
    with _connection() as connection:
        connection.execute(
            "INSERT INTO external_sources (id, course_id, url, source_type, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'queued', ?, ?)",
            (source_id, course_id, url, source_type, timestamp, timestamp),
        )
    return get_external_source(course_id, source_id)


def update_external_source(source_id: str, **fields: Any) -> None:
    allowed = {"title", "status", "content", "metadata_json", "error"}
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return
    if "metadata_json" in updates and not isinstance(updates["metadata_json"], str):
        updates["metadata_json"] = json.dumps(updates["metadata_json"], ensure_ascii=False)
    assignments = ", ".join(f"{key} = ?" for key in updates)
    with _connection() as connection:
        connection.execute(
            f"UPDATE external_sources SET {assignments}, updated_at = ? WHERE id = ?",
            (*updates.values(), _now(), source_id),
        )


def get_external_source(course_id: str, source_id: str) -> dict[str, Any]:
    with _connection() as connection:
        row = connection.execute(
            "SELECT * FROM external_sources WHERE id = ? AND course_id = ?",
            (source_id, course_id),
        ).fetchone()
    if row is None:
        raise KeyError("外部来源不存在")
    return {
        "id": str(row["id"]),
        "courseId": str(row["course_id"]),
        "url": str(row["url"]),
        "sourceType": str(row["source_type"]),
        "title": str(row["title"]),
        "status": str(row["status"]),
        "content": str(row["content"]),
        "metadata": json.loads(row["metadata_json"]),
        "error": str(row["error"]),
    }


GLOSSARY_IMPORTANCE_VALUES = {"core", "extended"}
GLOSSARY_STATUS_VALUES = {"draft", "active", "inactive"}


def glossary_match_key(term: str) -> str:
    """术语归一化匹配键：去空白/连字符/间隔号后小写，用于 (course_id, match_key) 唯一去重。"""
    return re.sub(r"[\s\-_·]", "", term).casefold()


def _glossary_term_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "courseId": str(row["course_id"]),
        "term": str(row["term"]),
        "matchKey": str(row["match_key"]),
        "aliases": json.loads(row["aliases_json"]),
        "oneLiner": str(row["one_liner"]),
        "article": str(row["article"]),
        "examTips": json.loads(row["exam_tips_json"]),
        "pitfalls": json.loads(row["pitfalls_json"]),
        "knowledgePointId": str(row["knowledge_point_id"]),
        "relatedKnowledgePointIds": json.loads(row["related_knowledge_point_ids_json"]),
        "moduleId": str(row["module_id"]),
        "importance": str(row["importance"]),
        "status": str(row["status"]),
        "origin": str(row["origin"]),
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
    }


def upsert_glossary_term(course_id: str, term_data: dict[str, Any], *, origin: str = "curator") -> dict[str, Any]:
    """按 (course_id, match_key) 幂等写入词条。

    - 已存在且 origin=manual：只合并新别名，正文/状态一律不动（用户手动编辑优先于 AI 刷新）。
    - 已存在且 origin=curator：全量覆盖内容字段并复活为 active。
    - 不存在：插入，active 起步（占位词条可传 status='draft'）。
    """
    initialize_agent_database()
    term = str(term_data.get("term", "")).strip()
    if not term:
        raise ValueError("术语名不能为空")
    match_key = glossary_match_key(term)
    aliases = [str(alias).strip() for alias in term_data.get("aliases", []) if str(alias).strip()]
    timestamp = _now()
    existing_row = None
    with _connection() as connection:
        existing_row = connection.execute(
            "SELECT * FROM glossary_terms WHERE course_id = ? AND match_key = ?",
            (course_id, match_key),
        ).fetchone()
        if existing_row is None:
            term_id = f"term-{uuid.uuid4().hex[:12]}"
            connection.execute(
                """
                INSERT INTO glossary_terms (
                    id, course_id, term, match_key, aliases_json, one_liner, article,
                    exam_tips_json, pitfalls_json, knowledge_point_id,
                    related_knowledge_point_ids_json, module_id, importance, status,
                    origin, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    term_id,
                    course_id,
                    term,
                    match_key,
                    json.dumps(aliases, ensure_ascii=False),
                    str(term_data.get("one_liner", "")),
                    str(term_data.get("article", "")),
                    json.dumps(list(term_data.get("exam_tips", [])), ensure_ascii=False),
                    json.dumps(list(term_data.get("pitfalls", [])), ensure_ascii=False),
                    str(term_data.get("knowledge_point_id", "")),
                    json.dumps(list(term_data.get("related_knowledge_point_ids", [])), ensure_ascii=False),
                    str(term_data.get("module_id", "")),
                    str(term_data.get("importance", "core")),
                    str(term_data.get("status", "active")),
                    origin,
                    timestamp,
                    timestamp,
                ),
            )
        elif str(existing_row["origin"]) == "manual" and origin == "curator":
            merged_aliases = list(dict.fromkeys(json.loads(existing_row["aliases_json"]) + aliases))
            connection.execute(
                "UPDATE glossary_terms SET aliases_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(merged_aliases, ensure_ascii=False), timestamp, str(existing_row["id"])),
            )
        else:
            connection.execute(
                """
                UPDATE glossary_terms SET
                    term = ?, aliases_json = ?, one_liner = ?, article = ?,
                    exam_tips_json = ?, pitfalls_json = ?, knowledge_point_id = ?,
                    related_knowledge_point_ids_json = ?, module_id = ?, importance = ?,
                    status = 'active', updated_at = ?
                WHERE id = ?
                """,
                (
                    term,
                    json.dumps(aliases, ensure_ascii=False),
                    str(term_data.get("one_liner", existing_row["one_liner"])),
                    str(term_data.get("article", existing_row["article"])),
                    json.dumps(list(term_data.get("exam_tips", json.loads(existing_row["exam_tips_json"]))), ensure_ascii=False),
                    json.dumps(list(term_data.get("pitfalls", json.loads(existing_row["pitfalls_json"]))), ensure_ascii=False),
                    str(term_data.get("knowledge_point_id", existing_row["knowledge_point_id"])),
                    json.dumps(list(term_data.get("related_knowledge_point_ids", json.loads(existing_row["related_knowledge_point_ids_json"]))), ensure_ascii=False),
                    str(term_data.get("module_id", existing_row["module_id"])),
                    str(term_data.get("importance", existing_row["importance"])),
                    timestamp,
                    str(existing_row["id"]),
                ),
            )
        row = connection.execute(
            "SELECT * FROM glossary_terms WHERE course_id = ? AND match_key = ?",
            (course_id, match_key),
        ).fetchone()
    assert row is not None
    return _glossary_term_row_to_dict(row)


def list_glossary_terms(course_id: str, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    initialize_agent_database()
    with _connection() as connection:
        if include_inactive:
            rows = connection.execute(
                "SELECT * FROM glossary_terms WHERE course_id = ? ORDER BY importance DESC, term",
                (course_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM glossary_terms WHERE course_id = ? AND status != 'inactive' ORDER BY importance DESC, term",
                (course_id,),
            ).fetchall()
    return [_glossary_term_row_to_dict(row) for row in rows]


def get_glossary_term(course_id: str, term_id: str) -> dict[str, Any]:
    with _connection() as connection:
        row = connection.execute(
            "SELECT * FROM glossary_terms WHERE id = ? AND course_id = ?",
            (term_id, course_id),
        ).fetchone()
    if row is None:
        raise KeyError("术语词条不存在")
    return _glossary_term_row_to_dict(row)


GLOSSARY_EDITABLE_COLUMNS = {
    "term": "term",
    "one_liner": "one_liner",
    "article": "article",
    "knowledge_point_id": "knowledge_point_id",
    "module_id": "module_id",
    "importance": "importance",
    "status": "status",
}


def update_glossary_term_fields(course_id: str, term_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """手动编辑词条：只更新白名单列，置 origin='manual'，改 term 时同步重算 match_key。"""
    updates = {key: value for key, value in fields.items() if key in GLOSSARY_EDITABLE_COLUMNS}
    if not updates:
        return get_glossary_term(course_id, term_id)
    if "importance" in updates and updates["importance"] not in GLOSSARY_IMPORTANCE_VALUES:
        raise ValueError("importance 取值无效")
    if "status" in updates and updates["status"] not in GLOSSARY_STATUS_VALUES:
        raise ValueError("status 取值无效")
    for list_field in ("aliases", "exam_tips", "pitfalls", "related_knowledge_point_ids"):
        if list_field in fields:
            updates[list_field] = [str(item) for item in fields[list_field]]
    if "term" in updates:
        term = str(updates["term"]).strip()
        if not term:
            raise ValueError("术语名不能为空")
        updates["term"] = term
        updates["match_key"] = glossary_match_key(term)
    column_values: dict[str, Any] = {}
    for key, value in updates.items():
        if key in {"aliases", "exam_tips", "pitfalls", "related_knowledge_point_ids"}:
            column_values[f"{key}_json"] = json.dumps(value, ensure_ascii=False)
        elif key == "match_key":
            column_values["match_key"] = value
        else:
            column_values[key] = value
    assignments = ", ".join(f"{key} = ?" for key in column_values)
    with _connection() as connection:
        changed = connection.execute(
            f"UPDATE glossary_terms SET {assignments}, origin = 'manual', updated_at = ? WHERE id = ? AND course_id = ?",
            (*column_values.values(), _now(), term_id, course_id),
        ).rowcount
    if not changed:
        raise KeyError("术语词条不存在")
    return get_glossary_term(course_id, term_id)


def delete_glossary_term(course_id: str, term_id: str) -> None:
    with _connection() as connection:
        changed = connection.execute(
            "DELETE FROM glossary_terms WHERE id = ? AND course_id = ?",
            (term_id, course_id),
        ).rowcount
    if not changed:
        raise KeyError("术语词条不存在")


def set_glossary_terms_status(course_id: str, match_keys: list[str], status: str) -> int:
    """按 match_key 批量切换状态（增量刷新用于失活/恢复），只影响 curator 词条。返回受影响行数。"""
    if status not in GLOSSARY_STATUS_VALUES:
        raise ValueError("status 取值无效")
    if not match_keys:
        return 0
    placeholders = ", ".join("?" for _ in match_keys)
    with _connection() as connection:
        changed = connection.execute(
            f"UPDATE glossary_terms SET status = ?, updated_at = ? WHERE course_id = ? AND match_key IN ({placeholders}) AND origin = 'curator'",
            (status, _now(), course_id, *match_keys),
        ).rowcount
    return int(changed)


def get_glossary_refresh_state(course_id: str) -> dict[str, Any]:
    initialize_agent_database()
    with _connection() as connection:
        row = connection.execute(
            "SELECT * FROM glossary_refresh_state WHERE course_id = ?",
            (course_id,),
        ).fetchone()
    if row is None:
        return {
            "courseId": course_id,
            "status": "idle",
            "contentSignature": "",
            "termsTotal": 0,
            "termsActive": 0,
            "lastError": "",
            "lastRefreshedAt": "",
            "phase": "idle",
            "candidatesTotal": 0,
            "termsCompleted": 0,
            "startedAt": "",
            "progressUpdatedAt": "",
        }
    return {
        "courseId": str(row["course_id"]),
        "status": str(row["status"]),
        "contentSignature": str(row["content_signature"]),
        "termsTotal": int(row["terms_total"]),
        "termsActive": int(row["terms_active"]),
        "lastError": str(row["last_error"]),
        "lastRefreshedAt": str(row["last_refreshed_at"]),
        "phase": str(row["phase"]),
        "candidatesTotal": int(row["candidates_total"]),
        "termsCompleted": int(row["terms_completed"]),
        "startedAt": str(row["started_at"]),
        "progressUpdatedAt": str(row["progress_updated_at"]),
    }


def save_glossary_refresh_state(course_id: str, **fields: Any) -> dict[str, Any]:
    allowed = {
        "status", "content_signature", "terms_total", "terms_active", "last_error", "last_refreshed_at",
        "phase", "candidates_total", "terms_completed", "started_at", "progress_updated_at",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    with _connection() as connection:
        row = connection.execute(
            "SELECT course_id FROM glossary_refresh_state WHERE course_id = ?",
            (course_id,),
        ).fetchone()
        if row is None:
            columns = ["course_id", *updates.keys()]
            placeholders = ", ".join("?" for _ in columns)
            connection.execute(
                f"INSERT INTO glossary_refresh_state ({', '.join(columns)}) VALUES ({placeholders})",
                (course_id, *updates.values()),
            )
        else:
            assignments = ", ".join(f"{key} = ?" for key in updates)
            connection.execute(
                f"UPDATE glossary_refresh_state SET {assignments} WHERE course_id = ?",
                (*updates.values(), course_id),
            )
    return get_glossary_refresh_state(course_id)
