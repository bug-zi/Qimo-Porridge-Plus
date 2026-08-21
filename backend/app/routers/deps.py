"""跨 router 共享的底层依赖：SQLite 连接、归档表辅助、当前用户（owner）。

路由模块只从这里 import，main.py 也从这里取 get_connection，
保持 main → routers 单向依赖，避免循环导入。
"""

from __future__ import annotations

import json
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


def purge_expired_archive_items(connection: sqlite3.Connection) -> None:
    connection.execute(
        "DELETE FROM archived_items WHERE purge_after <= ?",
        (datetime.now().isoformat(timespec="seconds"),),
    )


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
