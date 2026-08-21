"""跨 router 共享的底层依赖：SQLite 连接、归档表辅助。

路由模块只从这里 import，main.py 也从这里取 get_connection，
保持 main → routers 单向依赖，避免循环导入。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

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


def purge_expired_archive_items(connection: sqlite3.Connection) -> None:
    connection.execute(
        "DELETE FROM archived_items WHERE purge_after <= ?",
        (datetime.now().isoformat(timespec="seconds"),),
    )


def list_active_archive_items(connection: sqlite3.Connection) -> list[ArchiveItemResponse]:
    purge_expired_archive_items(connection)
    rows = connection.execute(
        """
        SELECT id, item_type, entity_id, title, course_id, course_name, deleted_at, purge_after
        FROM archived_items
        ORDER BY deleted_at DESC
        """
    ).fetchall()
    return [row_to_archive_item(row) for row in rows]


def create_archive_item(
    connection: sqlite3.Connection,
    *,
    item_type: Literal["course", "wrong-answer"],
    entity_id: str,
    title: str,
    payload: dict[str, Any],
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
            id, item_type, entity_id, title, course_id, course_name, payload, deleted_at, purge_after
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            archive_id,
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
