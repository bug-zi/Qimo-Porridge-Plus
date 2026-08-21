from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..agent_runtime import get_agent_job, get_agent_run
from ..study_service import agent_chat, agent_chat_stream

router = APIRouter()


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1)
    mode: Literal["chat", "agent"] = "chat"
    context: dict[str, Any] | None = None


@router.post("/api/courses/{course_id}/agent/chat")
def chat_with_course_agent(
    course_id: str,
    payload: AgentChatRequest,
) -> dict[str, Any]:
    try:
        message = payload.message.strip()
        return agent_chat(message, course_id, mode=payload.mode, context=payload.context)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/api/courses/{course_id}/agent/chat/stream")
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


@router.get("/api/agent-runs/{run_id}")
def agent_run_status(run_id: str) -> dict[str, Any]:
    try:
        return get_agent_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/api/agent-jobs/{job_id}")
def agent_job_status(job_id: str) -> dict[str, Any]:
    try:
        return get_agent_job(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
