from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Literal

from ..course_style_templates import CourseContentStyle, DEFAULT_COURSE_CONTENT_STYLE
from urllib.error import HTTPError, URLError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..agent_runtime import enqueue_agent_job, last_proposal_resolution_at, list_pending_proposals
from ..knowledge_service import (
    get_knowledge_status,
    rebuild_course_embeddings,
    retrieve_material_context,
)
from ..study_service import (
    build_daily_progress,
    create_course_workspace,
    generate_mind_map,
    get_strategy_documents,
    load_mind_map,
    load_workspace,
    mark_strategy_maintenance_pending,
    regroup_course_modules,
    replan_review_mainline,
    review_course_readability,
    save_course_setup,
    save_mind_map,
    save_workspace,
    submit_course_diagnostic,
    sync_course_knowledge,
    update_course_plan_params,
    update_workspace_state,
)
from .deps import (
    ArchiveItemResponse,
    course_is_owned,
    create_archive_item,
    current_owner_id,
    get_connection,
    list_active_archive_items,
    permanently_delete_archive_item,
    purge_expired_archive_items,
    require_course_ownership,
)

router = APIRouter()


@router.post("/api/courses/{course_id}/readability-review")
def audit_course_readability(
    course_id: str,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return review_course_readability(course_id)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


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


class CourseSetupRequest(BaseModel):
    course_name: str = Field(min_length=1, max_length=80)
    exam_date: str = Field(default="", max_length=80)
    target_score: int = Field(ge=0, le=100)
    target_text: str = Field(default="", max_length=200)
    daily_hours: float = Field(gt=0, le=12)
    days: int = Field(ge=1, le=30)
    review_count: int = Field(default=0, ge=0)
    exam_format: str = Field(default="", max_length=1000)
    remarks: str = Field(default="", max_length=2000)
    content_style: CourseContentStyle = DEFAULT_COURSE_CONTENT_STYLE


class PlanParamsAdjustRequest(BaseModel):
    """计划生成后动态调整参数：三字段全部可选，但至少提供一个。"""
    exam_date: str | None = Field(default=None, max_length=80)
    days: int | None = Field(default=None, ge=1, le=30)
    daily_hours: float | None = Field(default=None, gt=0, le=12)


class DiagnosticSubmitRequest(BaseModel):
    answers: dict[str, int]


class WorkspaceUpdateRequest(BaseModel):
    tasks: list[dict[str, Any]] | None = None
    wrong_answers: list[dict[str, Any]] | None = None
    note: str | None = None


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


def row_to_course(row: sqlite3.Row) -> CourseResponse:
    return CourseResponse(
        id=row["id"],
        name=row["name"],
        exam_date=row["exam_date"],
        target_score=row["target_score"],
        daily_hours=row["daily_hours"],
        progress=row["progress"],
    )


def include_strategy_document_content(course_id: str, workspace: dict[str, Any]) -> dict[str, Any]:
    try:
        documents = get_strategy_documents(course_id)
    except (FileNotFoundError, ValueError):
        return workspace
    return {**workspace, "strategyDocuments": documents}


@router.get("/api/courses", response_model=list[CourseResponse])
def list_courses(owner_id: str = Depends(current_owner_id)) -> list[CourseResponse]:
    with get_connection() as connection:
        purge_expired_archive_items(connection)
        rows = connection.execute(
            """
            SELECT id, name, exam_date, target_score, daily_hours, progress
            FROM courses
            WHERE owner_id = ?
            ORDER BY created_at ASC
            """,
            (owner_id,),
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


@router.post("/api/courses", response_model=CourseResponse, status_code=201)
def create_course(payload: CourseCreate, owner_id: str = Depends(current_owner_id)) -> CourseResponse:
    course_id = f"course-{int(datetime.now().timestamp() * 1000)}"
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO courses (
                id, owner_id, name, exam_date, target_score, daily_hours, progress, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                course_id,
                owner_id,
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


@router.get("/api/courses/{course_id}/workspace")
def course_workspace(course_id: str, _owner_id: str = Depends(require_course_ownership)) -> dict[str, Any]:
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


@router.get("/api/courses/{course_id}/mind-map")
def course_mind_map(course_id: str, _owner_id: str = Depends(require_course_ownership)) -> dict[str, Any]:
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


@router.put("/api/courses/{course_id}/mind-map")
def update_course_mind_map(
    course_id: str,
    payload: dict[str, Any],
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        mind_map = save_mind_map(payload, course_id)
        return {"status": "ready", "courseId": course_id, "mindMap": mind_map}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/api/courses/{course_id}/mind-map/generate")
def generate_course_mind_map(course_id: str, _owner_id: str = Depends(require_course_ownership)) -> dict[str, Any]:
    try:
        mind_map = generate_mind_map(course_id)
        return {"status": "ready", "courseId": course_id, "mindMap": mind_map}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/api/courses/{course_id}/mind-map/regroup-modules")
def regroup_course_mind_map_modules(
    course_id: str,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        mind_map = regroup_course_modules(course_id)
        return {"status": "ready", "courseId": course_id, "mindMap": mind_map}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/api/courses/{course_id}/search")
def search_course(
    course_id: str,
    q: str = Query(min_length=1, max_length=200),
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
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


@router.post("/api/courses/{course_id}/setup")
def configure_course(
    course_id: str,
    payload: CourseSetupRequest,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
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


@router.post("/api/courses/{course_id}/plan/adjust")
def adjust_course_plan_params(
    course_id: str,
    payload: PlanParamsAdjustRequest,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
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


@router.post("/api/courses/{course_id}/diagnostic/submit")
def submit_course_diagnostic_answers(
    course_id: str,
    payload: DiagnosticSubmitRequest,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return include_strategy_document_content(course_id, submit_course_diagnostic(payload.answers, course_id))
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.put("/api/courses/{course_id}/workspace")
def update_course_workspace(
    course_id: str,
    payload: WorkspaceUpdateRequest,
    _owner_id: str = Depends(require_course_ownership),
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


@router.delete("/api/courses/{course_id}", response_model=ArchiveItemResponse)
def archive_course(course_id: str, owner_id: str = Depends(require_course_ownership)) -> ArchiveItemResponse:
    with get_connection() as connection:
        purge_expired_archive_items(connection)
        course = connection.execute(
            """
            SELECT id, name, exam_date, target_score, daily_hours, progress, created_at
            FROM courses
            WHERE id = ? AND owner_id = ?
            """,
            (course_id, owner_id),
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
                owner_id=owner_id,
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
            owner_id=owner_id,
            course_id=course_id,
            course_name=workspace_course.get("name"),
            payload={"storage": "workspace", "workspace": workspace},
        )
        workspace["course"] = {**workspace_course, "archivedAt": archive_item.deleted_at}
        save_workspace(workspace, course_id)
    return archive_item


@router.get("/api/courses/{course_id}/plan", response_model=list[PlanTaskResponse])
def get_course_plan(course_id: str, _owner_id: str = Depends(require_course_ownership)) -> list[PlanTaskResponse]:
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


@router.get("/api/courses/{course_id}/knowledge/status")
def course_knowledge_status(course_id: str, _owner_id: str = Depends(require_course_ownership)) -> dict[str, Any]:
    return get_knowledge_status(course_id)


@router.post("/api/courses/{course_id}/knowledge/reindex")
def reindex_course_knowledge(course_id: str, _owner_id: str = Depends(require_course_ownership)) -> dict[str, Any]:
    try:
        sync_course_knowledge(course_id)
        return rebuild_course_embeddings(course_id)
    except (RuntimeError, HTTPError, URLError, TimeoutError, OSError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/api/archive", response_model=list[ArchiveItemResponse])
def list_archive(owner_id: str = Depends(current_owner_id)) -> list[ArchiveItemResponse]:
    """当前用户的归档列表（fa730d1 误删后恢复，阶段2 起带 owner 过滤）。"""
    with get_connection() as connection:
        return list_active_archive_items(connection, owner_id)


@router.delete("/api/archive/{archive_id}")
def delete_archive_item(archive_id: str, owner_id: str = Depends(current_owner_id)) -> dict[str, Any]:
    """立即永久删除自己的归档项；课程项同时清理 data 下的全部课程数据。"""
    with get_connection() as connection:
        purge_expired_archive_items(connection)
        if not permanently_delete_archive_item(connection, archive_id, owner_id):
            raise HTTPException(status_code=404, detail="归档内容不存在或已超过 7 天")
        return {
            "deleted": True,
            "archive_items": [item.model_dump() for item in list_active_archive_items(connection, owner_id)],
        }


@router.post("/api/archive/{archive_id}/restore")
def restore_archive_item(archive_id: str, owner_id: str = Depends(current_owner_id)) -> dict[str, Any]:
    """恢复归档项（fa730d1 误删后恢复，阶段2 起仅能恢复自己的归档）。"""
    with get_connection() as connection:
        purge_expired_archive_items(connection)
        row = connection.execute(
            "SELECT * FROM archived_items WHERE id = ? AND owner_id = ?",
            (archive_id, owner_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="归档内容不存在或已超过 7 天")

        payload = json.loads(row["payload"])
        item_type = row["item_type"]
        if item_type == "course":
            if payload.get("storage") == "workspace":
                workspace = payload["workspace"]
                restored_course_id = str(workspace.get("course", {}).get("id", ""))
                save_workspace(workspace, restored_course_id)
                # workspace 归档的课程当时不在 courses 索引表里，恢复时补登记到当前用户名下
                connection.execute(
                    """
                    INSERT OR IGNORE INTO courses (
                        id, owner_id, name, exam_date, target_score, daily_hours, progress, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        restored_course_id,
                        owner_id,
                        workspace["course"].get("name", "未命名课程"),
                        workspace["course"].get("examDate", ""),
                        int(workspace["course"].get("targetScore", 0)),
                        float(workspace["course"].get("dailyHours", 0)),
                        int(workspace["course"].get("progress", 0)),
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
                course = row_to_course({"id": restored_course_id, **_workspace_course_fields(workspace["course"])})
                connection.execute("DELETE FROM archived_items WHERE id = ?", (archive_id,))
                return {
                    "item_type": item_type,
                    "course": course.model_dump(),
                    "workspace": workspace,
                    "archive_items": [item.model_dump() for item in list_active_archive_items(connection, owner_id)],
                }

            course_payload = payload["course"]
            connection.execute(
                """
                INSERT OR REPLACE INTO courses (
                    id, owner_id, name, exam_date, target_score, daily_hours, progress, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    course_payload["id"],
                    owner_id,
                    course_payload["name"],
                    course_payload["exam_date"],
                    course_payload["target_score"],
                    course_payload["daily_hours"],
                    course_payload.get("progress", 0),
                    course_payload.get("created_at", datetime.now().isoformat(timespec="seconds")),
                ),
            )
            connection.execute("DELETE FROM plan_tasks WHERE course_id = ?", (course_payload["id"],))
            connection.executemany(
                """
                INSERT OR REPLACE INTO plan_tasks (
                    id, course_id, title, duration, progress, priority, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        task["id"],
                        task["course_id"],
                        task["title"],
                        task["duration"],
                        task.get("progress", 0),
                        task["priority"],
                        task["status"],
                    )
                    for task in payload.get("planTasks", [])
                ],
            )
            connection.execute("DELETE FROM archived_items WHERE id = ?", (archive_id,))
            return {
                "item_type": item_type,
                "course": row_to_course(course_payload).model_dump(),
                "archive_items": [item.model_dump() for item in list_active_archive_items(connection, owner_id)],
            }

        if item_type == "wrong-answer":
            course_id = str(row["course_id"] or "")
            if not course_id:
                raise HTTPException(status_code=422, detail="归档错题缺少课程信息")
            if not course_is_owned(connection, course_id, owner_id):
                raise HTTPException(status_code=404, detail="课程不存在")
            try:
                workspace = load_workspace(course_id)
            except FileNotFoundError as error:
                raise HTTPException(status_code=404, detail=str(error)) from error

            wrong_answer = payload["wrongAnswer"]
            wrong_answers = workspace.setdefault("wrongAnswers", [])
            if not any(item.get("id") == wrong_answer.get("id") for item in wrong_answers):
                workspace["wrongAnswers"] = [wrong_answer, *wrong_answers]
            save_workspace(workspace, course_id)
            connection.execute("DELETE FROM archived_items WHERE id = ?", (archive_id,))
            return {
                "item_type": item_type,
                "workspace": workspace,
                "archive_items": [item.model_dump() for item in list_active_archive_items(connection, owner_id)],
            }

    raise HTTPException(status_code=422, detail="归档类型暂不支持恢复")


def _workspace_course_fields(course: dict[str, Any]) -> dict[str, Any]:
    """workspace.course（camelCase）→ courses 索引表字段（snake_case）的映射。"""
    return {
        "name": course.get("name", "未命名课程"),
        "exam_date": course.get("examDate", ""),
        "target_score": course.get("targetScore", 0),
        "daily_hours": course.get("dailyHours", 0),
        "progress": course.get("progress", 0),
    }
