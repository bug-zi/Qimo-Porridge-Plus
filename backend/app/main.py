from __future__ import annotations

import json
import mimetypes
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request as FastAPIRequest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .agent_runtime import (
    AgentJobWorker,
    delete_glossary_term,
    enqueue_agent_job,
    get_agent_job,
    get_agent_run,
    get_external_source,
    get_glossary_refresh_state,
    get_glossary_term,
    initialize_agent_database,
    last_proposal_resolution_at,
    list_glossary_terms,
    list_pending_proposals,
    update_glossary_term_fields,
)
from .agents.tools import apply_proposal, dismiss_proposal
from .external_source_service import (
    approve_external_source,
    dismiss_external_source,
    process_external_source_job,
    submit_external_source,
)
from .knowledge_service import (
    ensure_local_ollama_service,
    get_embedding_status,
    get_knowledge_status,
    initialize_knowledge_database,
    rebuild_course_embeddings,
    retrieve_material_context,
    save_embedding_config,
    test_embedding_connection,
)
from .mcp_gateway import (
    clear_bilibili_credentials,
    discover_mcp_tools,
    get_bilibili_credential_status,
    list_mcp_servers,
    save_bilibili_credentials,
    save_mcp_server,
    seed_mcp_presets,
    verify_bilibili_credentials,
)
from .study_service import (
    agent_chat,
    agent_chat_stream,
    approve_strategy_documents,
    build_material_preview,
    create_course_workspace,
    fetch_available_model_ids,
    generate_strategy_documents,
    generate_mind_map,
    get_runtime_model_api_key,
    get_runtime_model_profile,
    get_strategy_documents,
    load_mind_map,
    get_user_profile_prompt,
    load_workspace,
    maintain_review_plan,
    mark_strategy_maintenance_pending,
    clear_practice_answer,
    clear_mock_result,
    ensure_orientation_task,
    refresh_workspace_materials,
    regroup_course_modules,
    resolve_course_material_path,
    resolve_converted_material_pdf_path,
    save_workspace,
    save_mind_map,
    save_runtime_model_profile,
    save_strategy_documents,
    save_user_profile_prompt,
    delete_course_material,
    save_course_setup,
    submit_course_diagnostic,
    submit_mock_answers,
    submit_practice_answer,
    submit_wrong_answer_retry,
    sync_course_knowledge,
    upload_course_materials,
    update_workspace_state,
    update_course_prompt,
    record_time,
    delete_time_entry,
    build_daily_progress,
    rebalance_daily_plan,
    update_course_plan_params,
    replan_review_mainline,
    run_glossary_refresh_job,
)

DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "data"
DATABASE_PATH = DATA_DIRECTORY / "exam_booster.db"
ARCHIVE_RETENTION_DAYS = 7


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


# 用户「采纳/忽略」一条调整建议后，在此冷却时间内不再自动生成新建议，
# 避免计划仍超额时每次打开空间都补一条建议，造成「卡片永远不消失」的体验。
PROPOSAL_REBALANCE_COOLDOWN = timedelta(minutes=30)


def _recently_resolved_proposal(course_id: str) -> bool:
    resolved_at = last_proposal_resolution_at(course_id)
    if not resolved_at:
        return False
    try:
        return datetime.now() - datetime.fromisoformat(resolved_at) < PROPOSAL_REBALANCE_COOLDOWN
    except ValueError:
        return False


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


def get_connection() -> sqlite3.Connection:
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    # timeout=30：多用户并发写下等待锁而非立刻报 database is locked
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


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


class CourseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    exam_date: str
    target_score: int = Field(ge=0, le=100)
    daily_hours: float = Field(gt=0, le=24)


class CourseResponse(CourseCreate):
    id: str
    progress: int


class PlanTaskResponse(BaseModel):
    id: str
    course_id: str
    title: str
    duration: int
    progress: int
    priority: Literal["high", "medium", "low"]
    status: Literal["pending", "in-progress", "completed"]


class ModelProfileTestRequest(BaseModel):
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=200)


class ModelProfileTestResponse(BaseModel):
    success: bool
    message: str
    available_models: list[str] = Field(default_factory=list)


class RuntimeModelUpdateRequest(BaseModel):
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str = Field(default="", max_length=500)
    model: str = Field(min_length=1, max_length=200)


class UserProfilePromptUpdateRequest(BaseModel):
    content: str = Field(default="", max_length=4000)


class EmbeddingConfigRequest(BaseModel):
    enabled: bool = True
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=200)




class CourseSetupRequest(BaseModel):
    course_name: str = Field(min_length=1, max_length=80)
    exam_date: str = Field(default="", max_length=80)
    target_score: int = Field(ge=0, le=100)
    target_text: str = Field(default="", max_length=200)
    daily_hours: float = Field(gt=0, le=12)
    days: int = Field(ge=1, le=30)
    review_count: int = Field(default=0, ge=0, le=30)
    exam_format: str = Field(default="", max_length=1000)
    remarks: str = Field(default="", max_length=2000)


class PlanParamsAdjustRequest(BaseModel):
    """计划生成后动态调整参数：三字段全部可选，但至少提供一个。"""
    exam_date: str | None = Field(default=None, max_length=80)
    days: int | None = Field(default=None, ge=1, le=30)
    daily_hours: float | None = Field(default=None, gt=0, le=12)


class PracticeAnswerRequest(BaseModel):
    question_id: str = Field(min_length=1, max_length=120)
    answer_index: int = Field(ge=0)
    mode: Literal["主线学习", "刷题练习"] = "刷题练习"


class WrongAnswerRetryRequest(BaseModel):
    answer_index: int = Field(ge=0)


class MockSubmitRequest(BaseModel):
    answers: dict[str, Any]


class DiagnosticSubmitRequest(BaseModel):
    answers: dict[str, int]


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1)
    mode: Literal["chat", "agent"] = "chat"
    context: dict[str, Any] | None = None


class WorkspaceUpdateRequest(BaseModel):
    tasks: list[dict[str, Any]] | None = None
    wrong_answers: list[dict[str, Any]] | None = None
    note: str | None = None


class TimeLogRequest(BaseModel):
    task_id: str = Field(default="", max_length=120)
    minutes: int = Field(ge=1, le=1440)
    target_date: str = Field(default="", max_length=10)
    note: str = Field(default="", max_length=200)


class StrategyDocumentsUpdateRequest(BaseModel):
    review_plan: str = Field(min_length=1)
    course_prompt: str = Field(min_length=1)
    review_plan_version: int = Field(ge=0)
    course_prompt_version: int = Field(ge=0)


class CoursePromptUpdateRequest(BaseModel):
    course_prompt: str = Field(min_length=1)
    version: int = Field(ge=0)


class McpServerUpdateRequest(BaseModel):
    id: str = Field(default="", max_length=120)
    name: str = Field(min_length=1, max_length=120)
    transport: Literal["http", "stdio"] = "http"
    endpoint: str = Field(default="", max_length=1000)
    command: str = Field(default="", max_length=300)
    args: list[str] = Field(default_factory=list, max_length=20)
    allowed_tools: list[str] = Field(min_length=1, max_length=40)


class BilibiliCredentialsRequest(BaseModel):
    sessdata: str = Field(min_length=1, max_length=512)
    bili_jct: str = Field(min_length=1, max_length=64)
    dedeuserid: str = Field(min_length=1, max_length=32)


class ExternalSourceRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    mcp_server_id: str = Field(min_length=1, max_length=120)
    tool_name: str = Field(min_length=1, max_length=200)
    source_type: Literal["web", "video", "note"] = "web"


class GlossaryTermUpdateRequest(BaseModel):
    term: str | None = Field(default=None, min_length=1, max_length=60)
    aliases: list[str] | None = Field(default=None, max_length=8)
    one_liner: str | None = Field(default=None, max_length=200)
    article: str | None = Field(default=None, max_length=4000)
    exam_tips: list[str] | None = Field(default=None, max_length=6)
    pitfalls: list[str] | None = Field(default=None, max_length=6)
    knowledge_point_id: str | None = None
    related_knowledge_point_ids: list[str] | None = Field(default=None, max_length=5)
    module_id: str | None = None
    importance: Literal["core", "extended"] | None = None
    status: Literal["draft", "active", "inactive"] | None = None


class GlossaryRefreshRequest(BaseModel):
    force: bool = False


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


def row_to_course(row: sqlite3.Row) -> CourseResponse:
    return CourseResponse(
        id=row["id"],
        name=row["name"],
        exam_date=row["exam_date"],
        target_score=row["target_score"],
        daily_hours=row["daily_hours"],
        progress=row["progress"],
    )


def course_payload_to_response(course: dict[str, Any]) -> CourseResponse:
    return CourseResponse(
        id=course["id"],
        name=course["name"],
        exam_date=course.get("exam_date", course.get("examDate")),
        target_score=course.get("target_score", course.get("targetScore")),
        daily_hours=course.get("daily_hours", course.get("dailyHours")),
        progress=course.get("progress", 0),
    )


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


def include_strategy_document_content(course_id: str, workspace: dict[str, Any]) -> dict[str, Any]:
    try:
        documents = get_strategy_documents(course_id)
    except (FileNotFoundError, ValueError):
        return workspace
    return {**workspace, "strategyDocuments": documents}


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


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "exam-booster-local-api"}


@app.get("/api/courses", response_model=list[CourseResponse])
def list_courses() -> list[CourseResponse]:
    with get_connection() as connection:
        purge_expired_archive_items(connection)
        rows = connection.execute(
            """
            SELECT id, name, exam_date, target_score, daily_hours, progress
            FROM courses
            ORDER BY created_at ASC
            """
        ).fetchall()
    courses = [row_to_course(row) for row in rows]
    for course in courses:
        try:
            load_workspace(course.id, refresh_materials=False)
        except FileNotFoundError:
            create_course_workspace(
                {
                    "id": course.id,
                    "name": course.name,
                    "examDate": course.exam_date,
                    "targetScore": course.target_score,
                    "dailyHours": course.daily_hours,
                    "progress": course.progress,
                    "color": "#3973e8",
                    "icon": "system",
                }
            )
    return courses


@app.post("/api/courses", response_model=CourseResponse, status_code=201)
def create_course(payload: CourseCreate) -> CourseResponse:
    course_id = f"course-{int(datetime.now().timestamp() * 1000)}"
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO courses (
                id, name, exam_date, target_score, daily_hours, progress, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                course_id,
                payload.name,
                payload.exam_date,
                payload.target_score,
                payload.daily_hours,
                0,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    response = CourseResponse(id=course_id, progress=0, **payload.model_dump())
    create_course_workspace(
        {
            "id": course_id,
            "name": payload.name,
            "examDate": payload.exam_date,
            "targetScore": payload.target_score,
            "dailyHours": payload.daily_hours,
            "progress": 0,
            "color": "#3973e8",
            "icon": "system",
        }
    )
    return response


@app.get("/api/courses/{course_id}/workspace")
def course_workspace(course_id: str) -> dict[str, Any]:
    try:
        workspace = load_workspace(course_id)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    progress = build_daily_progress(workspace)
    pending_proposals = list_pending_proposals(course_id)
    if (progress["overdue"] or progress["overBudget"]) and not pending_proposals and not _recently_resolved_proposal(course_id):
        try:
            enqueue_agent_job(course_id, "rebalance_daily_plan", {"event": "打开课程空间"}, max_attempts=1)
        except Exception:
            pass
    return include_strategy_document_content(
        course_id,
        {**workspace, "dailyProgress": progress, "pendingProposals": pending_proposals},
    )


@app.get("/api/courses/{course_id}/mind-map")
def course_mind_map(course_id: str) -> dict[str, Any]:
    try:
        mind_map = load_mind_map(course_id)
        return {"status": "ready", "courseId": course_id, "mindMap": mind_map}
    except FileNotFoundError:
        try:
            load_workspace(course_id, refresh_materials=False)
        except (FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"status": "empty", "courseId": course_id, "mindMap": None}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.put("/api/courses/{course_id}/mind-map")
def update_course_mind_map(course_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        mind_map = save_mind_map(payload, course_id)
        return {"status": "ready", "courseId": course_id, "mindMap": mind_map}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/courses/{course_id}/mind-map/generate")
def generate_course_mind_map(course_id: str) -> dict[str, Any]:
    try:
        mind_map = generate_mind_map(course_id)
        return {"status": "ready", "courseId": course_id, "mindMap": mind_map}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/courses/{course_id}/mind-map/regroup-modules")
def regroup_course_mind_map_modules(course_id: str) -> dict[str, Any]:
    try:
        mind_map = regroup_course_modules(course_id)
        return {"status": "ready", "courseId": course_id, "mindMap": mind_map}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/courses/{course_id}/search")
def search_course(course_id: str, q: str = Query(min_length=1, max_length=200)) -> dict[str, Any]:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="请输入搜索关键词")

    try:
        workspace = load_workspace(course_id, refresh_materials=False)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_result(
        result_id: str,
        result_type: str,
        module: str,
        title: str,
        excerpt: str,
        source: str = "",
    ) -> None:
        if result_id in seen or len(results) >= 30:
            return
        seen.add(result_id)
        results.append(
            {
                "id": result_id,
                "type": result_type,
                "module": module,
                "title": title,
                "excerpt": excerpt.strip()[:240],
                "source": source,
            }
        )

    try:
        material_matches = retrieve_material_context(course_id, query, limit=8)["items"]
    except (RuntimeError, ValueError, sqlite3.Error):
        material_matches = []
    for item in material_matches:
        add_result(
            f"material-{item['chunkId']}",
            "material",
            "materials",
            str(item["citation"]),
            str(item["content"]),
            str(item["source"]),
        )

    terms = [term for term in query.lower().split() if term]

    def matches(*values: Any) -> bool:
        text = " ".join(str(value) for value in values if value is not None).lower()
        return all(term in text for term in terms)

    for point in workspace.get("knowledgePoints", []):
        if matches(point.get("name"), point.get("summary"), point.get("source")):
            add_result(
                f"knowledge-{point.get('id', point.get('name', ''))}",
                "knowledge",
                "overview",
                str(point.get("name", "知识点")),
                str(point.get("summary", "")),
                str(point.get("source", "")),
            )

    note = str(workspace.get("note", ""))
    if matches(note):
        lowered_note = note.lower()
        match_at = min((lowered_note.find(term) for term in terms if term in lowered_note), default=0)
        excerpt_start = max(0, match_at - 70)
        add_result("course-note", "note", "notes", "课程复习笔记", note[excerpt_start:excerpt_start + 240])

    for wrong_answer in workspace.get("wrongAnswers", []):
        if matches(
            wrong_answer.get("title"),
            wrong_answer.get("tag"),
            wrong_answer.get("mistakeType"),
            wrong_answer.get("source"),
        ):
            add_result(
                f"wrong-answer-{wrong_answer.get('id', wrong_answer.get('title', ''))}",
                "wrong-answer",
                "errors",
                str(wrong_answer.get("title", "错题")),
                str(wrong_answer.get("mistakeType", "")),
                str(wrong_answer.get("source", wrong_answer.get("tag", ""))),
            )

    question_groups = (
        ("practiceQuestions", "practice", "刷题练习"),
        ("mockQuestions", "mock", "模拟卷"),
        ("diagnosticQuestions", "overview", "摸底测试"),
    )
    for field, module, source_label in question_groups:
        for question in workspace.get(field, []):
            if matches(
                question.get("prompt"),
                question.get("explanation"),
                question.get("source"),
                *question.get("options", []),
            ):
                add_result(
                    f"question-{field}-{question.get('id', question.get('prompt', ''))}",
                    "question",
                    module,
                    str(question.get("prompt", "练习题")),
                    str(question.get("explanation", "")),
                    str(question.get("source", source_label)),
                )

    return {"query": query, "results": results}


@app.post("/api/courses/{course_id}/setup")
def configure_course(course_id: str, payload: CourseSetupRequest) -> dict[str, Any]:
    try:
        workspace = save_course_setup(payload.model_dump(), course_id)
        with get_connection() as connection:
            connection.execute(
                """
                UPDATE courses
                SET name = ?, exam_date = ?, target_score = ?, daily_hours = ?
                WHERE id = ?
                """,
                (
                    workspace["course"]["name"],
                    workspace["course"]["examDate"],
                    workspace["course"]["targetScore"],
                    workspace["course"]["dailyHours"],
                    course_id,
                ),
            )
        return include_strategy_document_content(course_id, workspace)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.post("/api/courses/{course_id}/plan/adjust")
def adjust_course_plan_params(course_id: str, payload: PlanParamsAdjustRequest) -> dict[str, Any]:
    """计划生成后动态调整考试日期 / 复习天数 / 每日时间。

    - 仅 examDate 变（days/dailyHours 不变）：立即存参数，不重排，返回 {workspace, proposal: null}。
    - days 或 dailyHours 变：调 AI 生成携带新参数的重排提案，参数不落地，返回 {proposal, workspace: null}。
    """
    if payload.exam_date is None and payload.days is None and payload.daily_hours is None:
        raise HTTPException(status_code=422, detail="至少需要提供一个要调整的参数")
    try:
        workspace = load_workspace(course_id, refresh_materials=False)
        onboarding = workspace.get("onboarding") or {}
        course = workspace.get("course") or {}
        cur_exam = onboarding.get("examDate") or course.get("examDate", "")
        cur_days = int(onboarding.get("days") or 0)
        cur_hours = float(course.get("dailyHours") or onboarding.get("dailyHours") or 0)

        new_exam = (payload.exam_date if payload.exam_date is not None else cur_exam) or ""
        new_days = payload.days if payload.days is not None else cur_days
        new_hours = payload.daily_hours if payload.daily_hours is not None else cur_hours

        needs_replan = (new_days != cur_days) or (abs(new_hours - cur_hours) > 1e-9)

        if not needs_replan:
            # 轻量分支：只改考试日期，立即存参数，不重排
            updated = update_course_plan_params(course_id, exam_date=new_exam or None)
            with get_connection() as connection:
                connection.execute(
                    """
                    UPDATE courses
                    SET name = ?, exam_date = ?, target_score = ?, daily_hours = ?
                    WHERE id = ?
                    """,
                    (
                        updated["course"]["name"],
                        updated["course"]["examDate"],
                        updated["course"]["targetScore"],
                        updated["course"]["dailyHours"],
                        course_id,
                    ),
                )
            if new_exam != cur_exam and mark_strategy_maintenance_pending(course_id, "考试日期已更新"):
                enqueue_agent_job(course_id, "maintain_review_plan", {"event": "考试日期已更新"})
            return {"workspace": updated, "proposal": None}

        # 重排分支：调 AI 生成提案，参数不落地
        proposal = replan_review_mainline(
            course_id,
            new_exam_date=new_exam,
            new_days=new_days,
            new_daily_hours=new_hours,
        )
        return {"proposal": proposal, "workspace": None}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.post("/api/courses/{course_id}/diagnostic/submit")
def submit_course_diagnostic_answers(course_id: str, payload: DiagnosticSubmitRequest) -> dict[str, Any]:
    try:
        return include_strategy_document_content(course_id, submit_course_diagnostic(payload.answers, course_id))
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/api/courses/{course_id}/strategy-documents")
def course_strategy_documents(course_id: str) -> dict[str, Any]:
    try:
        return get_strategy_documents(course_id)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/courses/{course_id}/strategy-documents/generate")
def generate_course_strategy_documents(course_id: str) -> dict[str, Any]:
    try:
        return generate_strategy_documents(course_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.put("/api/courses/{course_id}/strategy-documents")
def update_course_strategy_documents(
    course_id: str,
    payload: StrategyDocumentsUpdateRequest,
) -> dict[str, Any]:
    try:
        return save_strategy_documents(
            course_id,
            payload.review_plan,
            payload.course_prompt,
            expected_review_plan_version=payload.review_plan_version,
            expected_course_prompt_version=payload.course_prompt_version,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/courses/{course_id}/strategy-documents/approve")
def approve_course_strategy_documents(
    course_id: str,
    payload: StrategyDocumentsUpdateRequest,
) -> dict[str, Any]:
    try:
        return include_strategy_document_content(
            course_id,
            approve_strategy_documents(
                course_id,
                payload.review_plan,
                payload.course_prompt,
                expected_review_plan_version=payload.review_plan_version,
                expected_course_prompt_version=payload.course_prompt_version,
            ),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        status_code = 409 if "已被更新" in str(error) else 502
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@app.post("/api/courses/{course_id}/strategy-documents/approve-job", status_code=202)
def enqueue_course_strategy_approval(
    course_id: str,
    payload: StrategyDocumentsUpdateRequest,
) -> dict[str, Any]:
    try:
        job_id = enqueue_agent_job(
            course_id,
            "approve_strategy_documents",
            {
                "reviewPlan": payload.review_plan,
                "coursePrompt": payload.course_prompt,
                "reviewPlanVersion": payload.review_plan_version,
                "coursePromptVersion": payload.course_prompt_version,
            },
            max_attempts=1,
        )
        return {"jobId": job_id, "courseId": course_id}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.put("/api/courses/{course_id}/course-prompt")
def save_course_prompt(course_id: str, payload: CoursePromptUpdateRequest) -> dict[str, Any]:
    try:
        return update_course_prompt(
            course_id,
            payload.course_prompt,
            expected_version=payload.version,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/courses/{course_id}/materials/preview/{material_path:path}")
def preview_course_material(course_id: str, material_path: str) -> dict[str, Any]:
    try:
        return build_material_preview(material_path, course_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/courses/{course_id}/materials/file/{material_path:path}")
def open_course_material(course_id: str, material_path: str) -> FileResponse:
    try:
        file_path = resolve_course_material_path(material_path, course_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(
        file_path,
        media_type=mimetypes.guess_type(file_path.name)[0] or "application/octet-stream",
        filename=file_path.name,
        content_disposition_type="inline",
    )


@app.get("/api/courses/{course_id}/materials/converted-file/{material_path:path}")
def open_converted_course_material(course_id: str, material_path: str) -> FileResponse:
    try:
        file_path = resolve_converted_material_pdf_path(material_path, course_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=f"{Path(material_path).stem}.pdf",
        content_disposition_type="inline",
    )


@app.post("/api/courses/{course_id}/materials/upload-batch")
async def upload_course_material_batch(
    course_id: str,
    request: FastAPIRequest,
) -> dict[str, Any]:
    try:
        payload = await request.body()
        header_end = payload.find(b"\n")
        if header_end <= 0:
            raise ValueError("批量上传数据格式无效")
        manifest_length = int(payload[:header_end].decode("ascii"))
        manifest_start = header_end + 1
        manifest_end = manifest_start + manifest_length
        manifest = json.loads(payload[manifest_start:manifest_end].decode("utf-8"))
        if not isinstance(manifest, list):
            raise ValueError("批量上传清单格式无效")
        files: list[tuple[str, bytes]] = []
        offset = manifest_end
        for item in manifest:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("size"), int):
                raise ValueError("批量上传清单字段无效")
            next_offset = offset + item["size"]
            if next_offset > len(payload):
                raise ValueError("批量上传文件内容不完整")
            files.append((item["name"], payload[offset:next_offset]))
            offset = next_offset
        if offset != len(payload):
            raise ValueError("批量上传数据长度不匹配")
        workspace = upload_course_materials(files, course_id)
        if mark_strategy_maintenance_pending(course_id, "课程资料发生变化"):
            enqueue_agent_job(course_id, "maintain_review_plan", {"event": "课程资料发生变化"})
            enqueue_agent_job(course_id, "glossary_refresh", {"event": "课程资料发生变化"}, max_attempts=2)
        return workspace
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.delete("/api/courses/{course_id}/materials/{material_path:path}")
def delete_generic_course_material(
    course_id: str,
    material_path: str,
) -> dict[str, Any]:
    try:
        workspace = delete_course_material(material_path, course_id)
        if mark_strategy_maintenance_pending(course_id, "课程资料发生变化"):
            enqueue_agent_job(course_id, "maintain_review_plan", {"event": "课程资料发生变化"})
            enqueue_agent_job(course_id, "glossary_refresh", {"event": "课程资料发生变化"}, max_attempts=2)
        return workspace
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/courses/{course_id}/materials/rescan")
def rescan_course_materials(
    course_id: str,
) -> dict[str, Any]:
    try:
        workspace = refresh_workspace_materials(course_id)
        if mark_strategy_maintenance_pending(course_id, "课程资料重新解析"):
            enqueue_agent_job(course_id, "maintain_review_plan", {"event": "课程资料重新解析"})
            enqueue_agent_job(course_id, "glossary_refresh", {"event": "课程资料重新解析"}, max_attempts=2)
        return workspace
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.put("/api/courses/{course_id}/workspace")
def update_course_workspace(
    course_id: str,
    payload: WorkspaceUpdateRequest,
) -> dict[str, Any]:
    try:
        before = load_workspace(course_id, refresh_materials=False)
        completed_before = sum(item.get("status") == "completed" for item in before.get("tasks", []))
        workspace = update_workspace_state(
            tasks=payload.tasks,
            wrong_answers=payload.wrong_answers,
            note=payload.note,
            course_id=course_id,
        )
        completed_after = sum(item.get("status") == "completed" for item in workspace.get("tasks", []))
        if completed_after > completed_before and mark_strategy_maintenance_pending(course_id, "复习任务完成"):
            enqueue_agent_job(course_id, "maintain_review_plan", {"event": "复习任务完成"})
        return workspace
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/courses/{course_id}/time-log")
def add_course_time_log(course_id: str, payload: TimeLogRequest) -> dict[str, Any]:
    try:
        return record_time(
            course_id,
            task_id=payload.task_id.strip() or None,
            minutes=payload.minutes,
            target_date=payload.target_date.strip() or None,
            note=payload.note,
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.delete("/api/courses/{course_id}/time-log/{entry_id}")
def remove_course_time_log(course_id: str, entry_id: str) -> dict[str, Any]:
    try:
        return delete_time_entry(course_id, entry_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/courses/{course_id}/practice/answer")
def answer_course_practice(course_id: str, payload: PracticeAnswerRequest) -> dict[str, Any]:
    try:
        return submit_practice_answer(payload.question_id, payload.answer_index, payload.mode, course_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def _archive_course_wrong_answer(course_id: str, wrong_answer_id: str) -> WrongAnswerArchiveResponse:
    try:
        workspace = load_workspace(course_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    wrong_answers = workspace.get("wrongAnswers", [])
    wrong_answer = next((item for item in wrong_answers if item.get("id") == wrong_answer_id), None)
    if wrong_answer is None:
        raise HTTPException(status_code=404, detail="错题不存在")

    course = workspace.get("course", {})
    with get_connection() as connection:
        archive_item = create_archive_item(
            connection,
            item_type="wrong-answer",
            entity_id=wrong_answer_id,
            title=wrong_answer.get("title", "未命名错题"),
            course_id=course_id,
            course_name=course.get("name"),
            payload={"wrongAnswer": wrong_answer},
        )
        workspace["wrongAnswers"] = [item for item in wrong_answers if item.get("id") != wrong_answer_id]
        save_workspace(workspace, course_id)
    return WrongAnswerArchiveResponse(workspace=workspace, archive_item=archive_item)


@app.delete(
    "/api/courses/{course_id}/wrong-answers/{wrong_answer_id}",
    response_model=WrongAnswerArchiveResponse,
)
def archive_course_wrong_answer(course_id: str, wrong_answer_id: str) -> WrongAnswerArchiveResponse:
    return _archive_course_wrong_answer(course_id, wrong_answer_id)


@app.post("/api/courses/{course_id}/wrong-answers/{wrong_answer_id}/retry")
def retry_course_wrong_answer(
    course_id: str,
    wrong_answer_id: str,
    payload: WrongAnswerRetryRequest,
) -> dict[str, Any]:
    try:
        result = submit_wrong_answer_retry(wrong_answer_id, payload.answer_index, course_id)
        if result.get("correct") and mark_strategy_maintenance_pending(course_id, "错题复练完成"):
            enqueue_agent_job(course_id, "maintain_review_plan", {"event": "错题复练完成"})
        return result
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/courses/{course_id}/mock/submit")
def submit_course_mock(
    course_id: str,
    payload: MockSubmitRequest,
) -> dict[str, Any]:
    try:
        result = submit_mock_answers(payload.answers, course_id)
        if mark_strategy_maintenance_pending(course_id, "模拟卷提交"):
            enqueue_agent_job(course_id, "maintain_review_plan", {"event": "模拟卷提交"})
        return result
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.delete("/api/courses/{course_id}/practice/answers/{question_id}")
def clear_course_practice_answer(course_id: str, question_id: str) -> dict[str, Any]:
    try:
        return clear_practice_answer(question_id, course_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.delete("/api/courses/{course_id}/mock/result")
def clear_course_mock_result(course_id: str) -> dict[str, Any]:
    try:
        return clear_mock_result(course_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/courses/{course_id}/agent/chat")
def chat_with_course_agent(
    course_id: str,
    payload: AgentChatRequest,
) -> dict[str, Any]:
    try:
        message = payload.message.strip()
        return agent_chat(message, course_id, mode=payload.mode, context=payload.context)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/courses/{course_id}/agent/chat/stream")
def chat_with_course_agent_stream(course_id: str, payload: AgentChatRequest):
    def event_source():
        try:
            for chunk in agent_chat_stream(
                payload.message.strip(),
                course_id,
                mode=payload.mode,
                context=payload.context,
            ):
                yield chunk
        except Exception as error:
            message = "课程尚未初始化。" if isinstance(error, FileNotFoundError) else "AI 伴学暂时无法响应，请稍后再试。"
            payload_str = json.dumps({"message": message}, ensure_ascii=False)
            yield f"event: error\ndata: {payload_str}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/courses/{course_id}/adjustment-proposals/{proposal_id}/apply")
def apply_course_adjustment_proposal(course_id: str, proposal_id: str) -> dict[str, Any]:
    try:
        workspace, proposal = apply_proposal(
            course_id,
            proposal_id,
            load_workspace=lambda value: load_workspace(value, refresh_materials=False),
            save_workspace=save_workspace,
        )
        # 携带参数的提案（replan 类）被采纳时，apply_proposal 已把参数写进 workspace.json，
        # 这里同步 SQLite courses 索引表。
        if proposal.get("params"):
            with get_connection() as connection:
                connection.execute(
                    """
                    UPDATE courses
                    SET name = ?, exam_date = ?, target_score = ?, daily_hours = ?
                    WHERE id = ?
                    """,
                    (
                        workspace["course"]["name"],
                        workspace["course"]["examDate"],
                        workspace["course"]["targetScore"],
                        workspace["course"]["dailyHours"],
                        course_id,
                    ),
                )
        if mark_strategy_maintenance_pending(course_id, "用户确认调整复习计划"):
            enqueue_agent_job(course_id, "maintain_review_plan", {"event": "用户确认调整复习计划"})
        # 主线重排（restructure_modules）或参数变更（replan 类提案）被采纳后，
        # 第0天·复习导引的阶段划分/依赖分层可能已过时，异步重建（签名缓存兜底，内容未变时零成本）。
        touches_mainline = bool(proposal.get("params")) or any(
            str(operation.get("type", "")) == "restructure_modules"
            for operation in proposal.get("operations", [])
        )
        if touches_mainline:
            enqueue_agent_job(course_id, "orientation_refresh", {"event": "提案被采纳"}, max_attempts=1)
        return {"workspace": workspace, "proposal": proposal}
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/courses/{course_id}/adjustment-proposals/{proposal_id}/dismiss")
def dismiss_course_adjustment_proposal(course_id: str, proposal_id: str) -> dict[str, Any]:
    try:
        return dismiss_proposal(course_id, proposal_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/agent-runs/{run_id}")
def agent_run_status(run_id: str) -> dict[str, Any]:
    try:
        return get_agent_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/agent-jobs/{job_id}")
def agent_job_status(job_id: str) -> dict[str, Any]:
    try:
        return get_agent_job(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/mcp/servers")
def mcp_servers() -> list[dict[str, Any]]:
    return list_mcp_servers()


@app.put("/api/mcp/servers")
def update_mcp_server(payload: McpServerUpdateRequest) -> dict[str, Any]:
    try:
        return save_mcp_server(
            payload.name,
            payload.endpoint,
            payload.allowed_tools,
            payload.id,
            transport=payload.transport,
            command=payload.command,
            args=payload.args,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/mcp/servers/{server_id}/discover")
def discover_mcp_server_tools(server_id: str) -> dict[str, Any]:
    try:
        return discover_mcp_tools(server_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (RuntimeError, OSError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/api/mcp/bilibili/credentials")
def bilibili_credentials_status() -> dict[str, Any]:
    return get_bilibili_credential_status()


@app.get("/api/mcp/bilibili/credentials/verify")
def bilibili_credentials_verify() -> dict[str, Any]:
    try:
        return verify_bilibili_credentials()
    except (RuntimeError, OSError, ValueError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.put("/api/mcp/bilibili/credentials")
def save_bilibili_credentials_endpoint(payload: BilibiliCredentialsRequest) -> dict[str, Any]:
    try:
        return save_bilibili_credentials(payload.sessdata, payload.bili_jct, payload.dedeuserid)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.delete("/api/mcp/bilibili/credentials")
def clear_bilibili_credentials_endpoint() -> dict[str, Any]:
    return clear_bilibili_credentials()


@app.get("/api/courses/{course_id}/glossary")
def get_course_glossary(course_id: str) -> dict[str, Any]:
    try:
        load_workspace(course_id, refresh_materials=False)
        return {
            "courseId": course_id,
            "terms": list_glossary_terms(course_id),
            "status": get_glossary_refresh_state(course_id),
        }
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/courses/{course_id}/glossary/status")
def get_course_glossary_status(course_id: str) -> dict[str, Any]:
    try:
        load_workspace(course_id, refresh_materials=False)
        return get_glossary_refresh_state(course_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.put("/api/courses/{course_id}/glossary/terms/{term_id}")
def update_course_glossary_term(course_id: str, term_id: str, payload: GlossaryTermUpdateRequest) -> dict[str, Any]:
    try:
        fields = {key: value for key, value in payload.model_dump().items() if value is not None}
        if not fields:
            raise ValueError("至少需要提供一个待更新字段")
        term = update_glossary_term_fields(course_id, term_id, fields)
        return {
            "courseId": course_id,
            "term": term,
            "status": get_glossary_refresh_state(course_id),
        }
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.delete("/api/courses/{course_id}/glossary/terms/{term_id}")
def delete_course_glossary_term(course_id: str, term_id: str) -> dict[str, Any]:
    try:
        delete_glossary_term(course_id, term_id)
        return {
            "courseId": course_id,
            "terms": list_glossary_terms(course_id),
            "status": get_glossary_refresh_state(course_id),
        }
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/courses/{course_id}/glossary/refresh", status_code=202)
def refresh_course_glossary(course_id: str, payload: GlossaryRefreshRequest | None = None) -> dict[str, Any]:
    try:
        load_workspace(course_id, refresh_materials=False)
        force = bool(payload.force) if payload else False
        job_id = enqueue_agent_job(
            course_id,
            "glossary_refresh",
            {"event": "手动刷新", "force": force},
            max_attempts=2,
        )
        return {"jobId": job_id, "courseId": course_id}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/courses/{course_id}/external-sources", status_code=202)
def import_external_course_source(course_id: str, payload: ExternalSourceRequest) -> dict[str, Any]:
    try:
        load_workspace(course_id, refresh_materials=False)
        return submit_external_source(
            course_id,
            payload.url,
            server_id=payload.mcp_server_id,
            tool_name=payload.tool_name,
            source_type=payload.source_type,
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/courses/{course_id}/external-sources/{source_id}")
def external_course_source(course_id: str, source_id: str) -> dict[str, Any]:
    try:
        return get_external_source(course_id, source_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/courses/{course_id}/external-sources/{source_id}/approve")
def approve_external_course_source(course_id: str, source_id: str) -> dict[str, Any]:
    try:
        return approve_external_source(course_id, source_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/courses/{course_id}/external-sources/{source_id}/dismiss")
def dismiss_external_course_source(course_id: str, source_id: str) -> dict[str, Any]:
    try:
        return dismiss_external_source(course_id, source_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.delete("/api/courses/{course_id}", response_model=ArchiveItemResponse)
def archive_course(course_id: str) -> ArchiveItemResponse:
    with get_connection() as connection:
        purge_expired_archive_items(connection)
        course = connection.execute(
            """
            SELECT id, name, exam_date, target_score, daily_hours, progress, created_at
            FROM courses
            WHERE id = ?
            """,
            (course_id,),
        ).fetchone()
        if course is not None:
            plan_tasks = connection.execute(
                """
                SELECT id, course_id, title, duration, progress, priority, status
                FROM plan_tasks
                WHERE course_id = ?
                """,
                (course_id,),
            ).fetchall()
            archive_item = create_archive_item(
                connection,
                item_type="course",
                entity_id=course_id,
                title=course["name"],
                course_id=course_id,
                course_name=course["name"],
                payload={
                    "storage": "database",
                    "course": dict(course),
                    "planTasks": [dict(task) for task in plan_tasks],
                },
            )
            connection.execute("DELETE FROM plan_tasks WHERE course_id = ?", (course_id,))
            connection.execute("DELETE FROM courses WHERE id = ?", (course_id,))
            return archive_item

    try:
        workspace = load_workspace(course_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="课程不存在") from error

    workspace_course = workspace.get("course", {})
    if workspace_course.get("id") != course_id:
        raise HTTPException(status_code=404, detail="课程不存在")

    with get_connection() as connection:
        archive_item = create_archive_item(
            connection,
            item_type="course",
            entity_id=course_id,
            title=workspace_course.get("name", "未命名课程"),
            course_id=course_id,
            course_name=workspace_course.get("name"),
            payload={"storage": "workspace", "workspace": workspace},
        )
        workspace["course"] = {**workspace_course, "archivedAt": archive_item.deleted_at}
        save_workspace(workspace, course_id)
    return archive_item


@app.get("/api/courses/{course_id}/plan", response_model=list[PlanTaskResponse])
def get_course_plan(course_id: str) -> list[PlanTaskResponse]:
    with get_connection() as connection:
        course = connection.execute("SELECT id FROM courses WHERE id = ?", (course_id,)).fetchone()
        if course is None:
            raise HTTPException(status_code=404, detail="课程不存在")
        rows = connection.execute(
            """
            SELECT id, course_id, title, duration, progress, priority, status
            FROM plan_tasks
            WHERE course_id = ?
            ORDER BY priority DESC, title ASC
            """,
            (course_id,),
        ).fetchall()
    return [PlanTaskResponse(**dict(row)) for row in rows]


@app.post("/api/model-profiles/test", response_model=ModelProfileTestResponse)
def test_model_profile(payload: ModelProfileTestRequest) -> ModelProfileTestResponse:
    base_url = payload.base_url.strip().rstrip("/")
    parsed_url = urlparse(base_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        raise HTTPException(status_code=422, detail="Base URL 必须是合法的 HTTP 或 HTTPS 地址")

    api_key = payload.api_key.strip() or get_runtime_model_api_key()
    if not api_key:
        return ModelProfileTestResponse(success=False, message="请先填写 API Key 或保存本机 API Key")

    try:
        available_models = fetch_available_model_ids(base_url, api_key)
        selected_model = payload.model.strip()
        if selected_model and available_models and selected_model not in available_models:
            return ModelProfileTestResponse(
                success=False,
                message="连接成功，但当前模型不在可用列表中",
                available_models=available_models,
            )
        model_count = len(available_models)
        message = f"连接成功，已读取 {model_count} 个可用模型" if model_count else "连接成功，但未读取到可用模型列表"
        return ModelProfileTestResponse(success=True, message=message, available_models=available_models)
    except HTTPError as error:
        return ModelProfileTestResponse(success=False, message=f"模型服务返回 HTTP {error.code}，请检查 API Key 和服务地址")
    except URLError:
        return ModelProfileTestResponse(success=False, message="无法连接模型服务，请检查 Base URL、网络或本地代理")
    except TimeoutError:
        return ModelProfileTestResponse(success=False, message="连接超时，请检查服务是否可用")
    except ValueError:
        return ModelProfileTestResponse(success=False, message="模型服务返回内容无法解析，请确认 /models 接口兼容 OpenAI 格式")


@app.get("/api/runtime-model")
def runtime_model() -> dict[str, str | bool | list[str]]:
    return get_runtime_model_profile()


@app.put("/api/runtime-model")
def update_runtime_model(payload: RuntimeModelUpdateRequest) -> dict[str, str | bool | list[str]]:
    base_url = payload.base_url.strip().rstrip("/")
    parsed_url = urlparse(base_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        raise HTTPException(status_code=422, detail="Base URL 必须是合法的 HTTP 或 HTTPS 地址")
    if not payload.api_key.strip() and not get_runtime_model_api_key():
        raise HTTPException(status_code=422, detail="请先填写 API Key")
    return save_runtime_model_profile(base_url, payload.api_key, payload.model)


@app.get("/api/user-profile")
def user_profile_prompt() -> dict[str, str]:
    return get_user_profile_prompt()


@app.put("/api/user-profile")
def update_user_profile_prompt(payload: UserProfilePromptUpdateRequest) -> dict[str, str]:
    try:
        return save_user_profile_prompt(payload.content)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/courses/{course_id}/knowledge/status")
def course_knowledge_status(course_id: str) -> dict[str, Any]:
    return get_knowledge_status(course_id)


@app.post("/api/courses/{course_id}/knowledge/reindex")
def reindex_course_knowledge(course_id: str) -> dict[str, Any]:
    try:
        sync_course_knowledge(course_id)
        return rebuild_course_embeddings(course_id)
    except (RuntimeError, HTTPError, URLError, TimeoutError, OSError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/knowledge/embedding")
def embedding_status() -> dict[str, Any]:
    return get_embedding_status()


@app.put("/api/knowledge/embedding")
def update_embedding_config(payload: EmbeddingConfigRequest) -> dict[str, Any]:
    try:
        return save_embedding_config({"enabled": payload.enabled, "baseUrl": payload.base_url, "model": payload.model})
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/knowledge/embedding/test")
def test_saved_embedding() -> dict[str, Any]:
    return test_embedding_connection()

