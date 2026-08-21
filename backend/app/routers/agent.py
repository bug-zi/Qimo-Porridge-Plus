from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..agent_runtime import get_agent_job, get_agent_run
from ..study_service import agent_chat, agent_chat_stream
from .deps import get_connection, course_is_owned, current_owner_id, require_course_ownership

router = APIRouter()


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1)
    mode: Literal["chat", "agent"] = "chat"
    context: dict[str, Any] | None = None


@router.post("/api/courses/{course_id}/agent/chat")
def chat_with_course_agent(
    course_id: str,
    payload: AgentChatRequest,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        message = payload.message.strip()
        return agent_chat(message, course_id, mode=payload.mode, context=payload.context)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/api/courses/{course_id}/agent/chat/stream")
def chat_with_course_agent_stream(
    course_id: str,
    payload: AgentChatRequest,
    _owner_id: str = Depends(require_course_ownership),
):
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


@router.get("/api/agent-runs/{run_id}")
def agent_run_status(run_id: str, owner_id: str = Depends(current_owner_id)) -> dict[str, Any]:
    try:
        run = get_agent_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    _ensure_agent_resource_owned(run["courseId"], owner_id)
    return run


@router.get("/api/agent-jobs/{job_id}")
def agent_job_status(job_id: str, owner_id: str = Depends(current_owner_id)) -> dict[str, Any]:
    try:
        job = get_agent_job(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    _ensure_agent_resource_owned(job["courseId"], owner_id)
    return job


def _ensure_agent_resource_owned(course_id: str, owner_id: str) -> None:
    """agent_runs / agent_jobs 以 courseId 反查课程归属（不通过 → 404，不泄露存在性）。"""
    with get_connection() as connection:
        if not course_is_owned(connection, course_id, owner_id):
            raise HTTPException(status_code=404, detail="任务不存在")
