"""多租户归属（阶段2）。

courses / archived_items 两表带 owner_id；存量无主数据在启动时归属首个注册用户。
其余业务表（plan_tasks / agent_jobs / artifacts / glossary / knowledge 等）
全部以 course_id 为索引——路由层校验课程归属后，这些表的数据即被传递隔离，
无需逐表加列。

运行时归属校验在 routers/deps.py：current_owner_id + require_course_ownership
（本模块只承担启动期迁移，避免与 deps 循环导入）。
"""

from __future__ import annotations

from .routers.deps import get_connection


def ensure_owner_columns() -> None:
    """给 courses / archived_items 补 owner_id 列（老库 ALTER 平滑升级；新库建表已带列）。"""
    with get_connection() as connection:
        for table in ("courses", "archived_items"):
            columns = {
                str(row["name"])
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if "owner_id" not in columns:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN owner_id TEXT NOT NULL DEFAULT ''"
                )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_courses_owner ON courses(owner_id)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_archived_items_owner ON archived_items(owner_id)"
        )


def claim_legacy_courses() -> None:
    """存量无主课程/归档归属首个注册用户；尚无用户时留待下次启动或首个注册时认领。"""
    with get_connection() as connection:
        first_user = connection.execute(
            "SELECT id FROM users ORDER BY created_at ASC, rowid ASC LIMIT 1"
        ).fetchone()
        if first_user is None:
            return
        owner_id = str(first_user["id"])
        connection.execute(
            "UPDATE courses SET owner_id = ? WHERE owner_id = ''",
            (owner_id,),
        )
        connection.execute(
            "UPDATE archived_items SET owner_id = ? WHERE owner_id = ''",
            (owner_id,),
        )
