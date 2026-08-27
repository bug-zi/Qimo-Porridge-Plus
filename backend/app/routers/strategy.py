from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..agent_runtime import enqueue_agent_job, get_active_agent_job
from ..agents.tools import apply_proposal, dismiss_proposal
from ..study_service import (
    approve_strategy_documents,
    generate_strategy_documents,
    get_strategy_documents,
    load_workspace,
    mark_strategy_maintenance_pending,
    revise_strategy_draft,
    save_strategy_documents,
    save_workspace,
    update_course_prompt,
)
from .courses import include_strategy_document_content
from .deps import get_connection, require_course_ownership

router = APIRouter()


class StrategyDocumentsUpdateRequest(BaseModel):
    review_plan: str = Field(min_length=1)
    course_prompt: str = Field(min_length=1)
    review_plan_version: int = Field(ge=0)
    course_prompt_version: int = Field(ge=0)
    repair_only: bool = False
    generation_mode: Literal["incremental", "all"] = "all"
    lesson_limit: int | None = Field(default=None, ge=1)
    continue_generation: bool = False


class CoursePromptUpdateRequest(BaseModel):
    course_prompt: str = Field(min_length=1)
    version: int = Field(ge=0)


class StrategyRevisionRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=20)
    review_plan: str = Field(min_length=1)
    course_prompt: str = Field(min_length=1)


@router.get("/api/courses/{course_id}/strategy-documents")
def course_strategy_documents(
    course_id: str,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return get_strategy_documents(course_id)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/api/courses/{course_id}/strategy-documents/generate")
def generate_course_strategy_documents(
    course_id: str,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return generate_strategy_documents(course_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.put("/api/courses/{course_id}/strategy-documents")
def update_course_strategy_documents(
    course_id: str,
    payload: StrategyDocumentsUpdateRequest,
    _owner_id: str = Depends(require_course_ownership),
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


@router.post("/api/courses/{course_id}/strategy-documents/approve")
def approve_course_strategy_documents(
    course_id: str,
    payload: StrategyDocumentsUpdateRequest,
    _owner_id: str = Depends(require_course_ownership),
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
                repair_only=payload.repair_only,
                generation_mode=payload.generation_mode,
                lesson_limit=payload.lesson_limit,
                continue_generation=payload.continue_generation,
            ),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        status_code = 409 if "已被更新" in str(error) else 502
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@router.get("/api/courses/{course_id}/strategy-documents/active-job")
def get_active_course_strategy_job(
    course_id: str,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    job = get_active_agent_job(course_id, "approve_strategy_documents")
    return {"job": job}


@router.post("/api/courses/{course_id}/strategy-documents/approve-job", status_code=202)
def enqueue_course_strategy_approval(
    course_id: str,
    payload: StrategyDocumentsUpdateRequest,
    _owner_id: str = Depends(require_course_ownership),
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
                "repairOnly": payload.repair_only,
                "generationMode": payload.generation_mode,
                "lessonLimit": payload.lesson_limit,
                "continueGeneration": payload.continue_generation,
            },
            max_attempts=1,
        )
        return {"jobId": job_id, "courseId": course_id}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.put("/api/courses/{course_id}/course-prompt")
def save_course_prompt(
    course_id: str,
    payload: CoursePromptUpdateRequest,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
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


@router.post("/api/courses/{course_id}/strategy-documents/revise")
def revise_course_strategy_documents(
    course_id: str,
    payload: StrategyRevisionRequest,
    _owner_id: str = Depends(require_course_ownership),
):
    """对话式修订策略草稿（SSE）。纯草稿变换：不落盘，确认仍走 approve 端点。"""

    def event_source():
        try:
            yield from revise_strategy_draft(
                course_id,
                payload.message.strip(),
                payload.history,
                payload.review_plan,
                payload.course_prompt,
                owner_id=_owner_id,
            )
        except FileNotFoundError as error:
            payload_str = json.dumps({"message": "课程不存在。"}, ensure_ascii=False)
            yield f"event: error\ndata: {payload_str}\n\n"
        except ValueError as error:
            payload_str = json.dumps({"message": str(error)}, ensure_ascii=False)
            yield f"event: error\ndata: {payload_str}\n\n"
        except Exception:
            payload_str = json.dumps({"message": "策略修订暂时无法响应，请稍后再试。"}, ensure_ascii=False)
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


@router.post("/api/courses/{course_id}/adjustment-proposals/{proposal_id}/apply")
def apply_course_adjustment_proposal(
    course_id: str,
    proposal_id: str,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
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


@router.post("/api/courses/{course_id}/adjustment-proposals/{proposal_id}/dismiss")
def dismiss_course_adjustment_proposal(
    course_id: str,
    proposal_id: str,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return dismiss_proposal(course_id, proposal_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
