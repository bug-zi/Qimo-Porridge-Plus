from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..agent_runtime import (
    delete_glossary_term,
    enqueue_agent_job,
    get_glossary_refresh_state,
    list_glossary_terms,
    update_glossary_term_fields,
)
from ..study_service import load_workspace
from .deps import require_course_ownership

router = APIRouter()


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


@router.get("/api/courses/{course_id}/glossary")
def get_course_glossary(course_id: str, _owner_id: str = Depends(require_course_ownership)) -> dict[str, Any]:
    try:
        load_workspace(course_id, refresh_materials=False)
        return {
            "courseId": course_id,
            "terms": list_glossary_terms(course_id),
            "status": get_glossary_refresh_state(course_id),
        }
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/api/courses/{course_id}/glossary/status")
def get_course_glossary_status(course_id: str, _owner_id: str = Depends(require_course_ownership)) -> dict[str, Any]:
    try:
        load_workspace(course_id, refresh_materials=False)
        return get_glossary_refresh_state(course_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.put("/api/courses/{course_id}/glossary/terms/{term_id}")
def update_course_glossary_term(
    course_id: str,
    term_id: str,
    payload: GlossaryTermUpdateRequest,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
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


@router.delete("/api/courses/{course_id}/glossary/terms/{term_id}")
def delete_course_glossary_term(
    course_id: str,
    term_id: str,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        delete_glossary_term(course_id, term_id)
        return {
            "courseId": course_id,
            "terms": list_glossary_terms(course_id),
            "status": get_glossary_refresh_state(course_id),
        }
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/api/courses/{course_id}/glossary/refresh", status_code=202)
def refresh_course_glossary(
    course_id: str,
    payload: GlossaryRefreshRequest | None = None,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
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
