from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agent_runtime import AgentJobWorker, initialize_agent_database
from .external_source_service import process_external_source_job
from .knowledge_service import (
    ensure_local_ollama_service,
    initialize_knowledge_database,
)
from .mcp_gateway import seed_mcp_presets
from .routers import agent as agent_router
from .routers import courses as courses_router
from .routers import external_sources as external_sources_router
from .routers import glossary as glossary_router
from .routers import mcp as mcp_router
from .routers import materials as materials_router
from .routers import practice as practice_router
from .routers import settings as settings_router
from .routers import strategy as strategy_router
from .routers import system as system_router
from .routers.deps import get_connection
from .study_service import (
    approve_strategy_documents,
    ensure_orientation_task,
    maintain_review_plan,
    rebalance_daily_plan,
    run_glossary_refresh_job,
    sync_course_knowledge,
)


def _maintain_plan_job(course_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    maintain_review_plan(course_id, str(payload.get("event", "学习状态变化")))
    return {"maintained": True}


def _approve_strategy_documents_job(course_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    approve_strategy_documents(
        course_id,
        str(payload.get("reviewPlan", "")),
        str(payload.get("coursePrompt", "")),
        expected_review_plan_version=int(payload.get("reviewPlanVersion", 0)),
        expected_course_prompt_version=int(payload.get("coursePromptVersion", 0)),
    )
    return {"courseId": course_id, "planned": True}


def _rebalance_plan_job(course_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    rebalance_daily_plan(course_id, str(payload.get("event", "每日时间核对")))
    return {"rebalanced": True}


def _glossary_refresh_job(course_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return run_glossary_refresh_job(
        course_id,
        str(payload.get("event", "")),
        force=bool(payload.get("force", False)),
    )


def _orientation_refresh_job(course_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    # 主线重排/参数变更后重建第0天·复习导引：build_orientation_guide 按模块+知识点
    # 签名缓存，内容未变时零成本命中，变化时走 LLM 重生成，失败时确定性兜底。
    ensure_orientation_task(course_id, force=True)
    return {"refreshed": True}


AGENT_JOB_WORKER = AgentJobWorker(
    {
        "maintain_review_plan": _maintain_plan_job,
        "external_source_import": process_external_source_job,
        "approve_strategy_documents": _approve_strategy_documents_job,
        "rebalance_daily_plan": _rebalance_plan_job,
        "glossary_refresh": _glossary_refresh_job,
        "orientation_refresh": _orientation_refresh_job,
    }
)


def initialize_database() -> None:
    with get_connection() as connection:
        # WAL 模式：读写不互斥，多用户并发下的关键配置（持久生效）
        connection.execute("PRAGMA journal_mode=WAL")
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS courses (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                exam_date TEXT NOT NULL,
                target_score INTEGER NOT NULL,
                daily_hours REAL NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS plan_tasks (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL,
                title TEXT NOT NULL,
                duration INTEGER NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                priority TEXT NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (course_id) REFERENCES courses(id)
            );

            CREATE TABLE IF NOT EXISTS archived_items (
                id TEXT PRIMARY KEY,
                item_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                title TEXT NOT NULL,
                course_id TEXT,
                course_name TEXT,
                payload TEXT NOT NULL,
                deleted_at TEXT NOT NULL,
                purge_after TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        seed_completed = connection.execute(
            "SELECT value FROM app_metadata WHERE key = ?",
            ("seed_courses_initialized",),
        ).fetchone()
        existing_course = connection.execute(
            "SELECT id FROM courses WHERE id = ?",
            ("data-structure",),
        ).fetchone()
        if seed_completed is None and existing_course is None:
            connection.execute(
                """
                INSERT INTO courses (
                    id, name, exam_date, target_score, daily_hours, progress, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "data-structure",
                    "数据结构",
                    "2026-07-31",
                    85,
                    4,
                    61,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            connection.executemany(
                """
                INSERT INTO plan_tasks (id, course_id, title, duration, progress, priority, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "task-graph",
                        "data-structure",
                        "图的遍历与最短路径",
                        120,
                        10,
                        "high",
                        "pending",
                    ),
                    (
                        "task-sort",
                        "data-structure",
                        "排序算法",
                        90,
                        5,
                        "high",
                        "pending",
                    ),
                ],
            )
        if seed_completed is None:
            connection.execute(
                "INSERT OR REPLACE INTO app_metadata (key, value) VALUES (?, ?)",
                ("seed_courses_initialized", "true"),
            )


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    initialize_knowledge_database()
    ensure_local_ollama_service()
    initialize_agent_database()
    seed_mcp_presets()
    try:
        sync_course_knowledge()
    except Exception:
        pass
    AGENT_JOB_WORKER.start()
    try:
        yield
    finally:
        AGENT_JOB_WORKER.stop()


app = FastAPI(
    title="期末粥加速器本地服务",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载顺序沿用拆分前 main.py 中路由的首次出现顺序；
# 各模块内部保持原有相对顺序，URL 匹配行为与拆分前一致。
app.include_router(system_router.router)
app.include_router(courses_router.router)
app.include_router(strategy_router.router)
app.include_router(materials_router.router)
app.include_router(practice_router.router)
app.include_router(agent_router.router)
app.include_router(mcp_router.router)
app.include_router(glossary_router.router)
app.include_router(external_sources_router.router)
app.include_router(settings_router.router)
