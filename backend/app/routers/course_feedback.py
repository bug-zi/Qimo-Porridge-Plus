from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..course_feedback_service import (
    apply_course_feedback_rewrite,
    apply_global_course_feedback,
    get_course_feedback_rules,
    list_course_feedback,
    refine_course_feedback_rewrite,
    submit_course_feedback_with_rewrite,
    submit_global_course_feedback,
)
from ..study_service import _model_json
from .deps import require_course_ownership

router = APIRouter()


class CourseFeedbackRequest(BaseModel):
    selected_text: str = Field(min_length=1, max_length=4000)
    user_comment: str = Field(min_length=1, max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)


@router.post("/api/courses/{course_id}/course-feedback")
def create_course_feedback(
    course_id: str,
    payload: CourseFeedbackRequest,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return submit_course_feedback_with_rewrite(
            course_id,
            selected_text=payload.selected_text,
            user_comment=payload.user_comment,
            context=payload.context,
            model_json=_model_json,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error




class CourseFeedbackRefineRequest(BaseModel):
    extra_comment: str = Field(min_length=1, max_length=2000)
    previous_rewrite: str = Field(min_length=1, max_length=8000)


class CourseFeedbackApplyRequest(BaseModel):
    target: dict[str, Any] = Field(default_factory=dict)
    original_text: str = Field(min_length=1, max_length=4000)
    rewritten_text: str = Field(min_length=0, max_length=8000)


@router.post("/api/courses/{course_id}/course-feedback/{feedback_id}/rewrite/refine")
def refine_feedback_rewrite(
    course_id: str,
    feedback_id: str,
    payload: CourseFeedbackRefineRequest,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return refine_course_feedback_rewrite(
            course_id,
            feedback_id,
            extra_comment=payload.extra_comment,
            previous_rewrite=payload.previous_rewrite,
            model_json=_model_json,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/api/courses/{course_id}/course-feedback/{feedback_id}/rewrite/apply")
def apply_feedback_rewrite(
    course_id: str,
    feedback_id: str,
    payload: CourseFeedbackApplyRequest,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return apply_course_feedback_rewrite(
            course_id,
            feedback_id,
            target=payload.target,
            original_text=payload.original_text,
            rewritten_text=payload.rewritten_text,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/api/courses/{course_id}/course-feedback")
def course_feedback_items(
    course_id: str,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return list_course_feedback(course_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/api/courses/{course_id}/course-feedback/rules")
def course_feedback_rules(
    course_id: str,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return get_course_feedback_rules(course_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

class GlobalCourseFeedbackRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=200)
    section_id: str = Field(min_length=1, max_length=100)
    section_index: int = Field(ge=0, le=3)
    user_comment: str = Field(min_length=1, max_length=2000)


@router.post("/api/courses/{course_id}/course-feedback/global")
def create_global_course_feedback(
    course_id: str,
    payload: GlobalCourseFeedbackRequest,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return submit_global_course_feedback(course_id, task_id=payload.task_id, section_id=payload.section_id, section_index=payload.section_index, user_comment=payload.user_comment, model_json=_model_json)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/api/courses/{course_id}/course-feedback/{feedback_id}/global/apply")
def apply_global_feedback(
    course_id: str,
    feedback_id: str,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return apply_global_course_feedback(course_id, feedback_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

