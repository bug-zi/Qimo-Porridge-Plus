from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..course_feedback_service import (
    abandon_course_feedback,
    apply_course_feedback_rewrite,
    apply_global_course_feedback,
    delete_course_feedback_rule,
    get_course_feedback_rules,
    get_open_course_feedback,
    list_course_feedback,
    merge_course_feedback_rules,
    retry_course_feedback_proposal,
    refine_course_feedback_rewrite,
    refine_global_course_feedback,
    submit_course_feedback_with_rewrite,
    submit_global_course_feedback,
    update_course_feedback_rule,
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
    # Kept for backward compatibility only; the service trusts its persisted latest proposal.
    previous_rewrite: str = Field(default="", max_length=8000)


class CourseFeedbackApplyRequest(BaseModel):
    # Legacy preview fields remain accepted, but apply uses the server-side latest proposal.
    target: dict[str, Any] = Field(default_factory=dict)
    original_text: str = Field(default="", max_length=4000)
    rewritten_text: str = Field(default="", max_length=8000)
    remember_preference: bool = True
    expected_revision: int | None = Field(default=None, ge=0)


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
            remember_preference=payload.remember_preference,
            expected_revision=payload.expected_revision,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/api/courses/{course_id}/course-feedback/{feedback_id}/proposal/retry")
def retry_feedback_proposal(course_id: str, feedback_id: str, _owner_id: str = Depends(require_course_ownership)) -> dict[str, Any]:
    try:
        return retry_course_feedback_proposal(course_id, feedback_id, model_json=_model_json)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/api/courses/{course_id}/course-feedback/{feedback_id}/abandon")
def abandon_feedback(course_id: str, feedback_id: str, _owner_id: str = Depends(require_course_ownership)) -> dict[str, Any]:
    try:
        return abandon_course_feedback(course_id, feedback_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/api/courses/{course_id}/course-feedback/open")
def open_feedback_sessions(course_id: str, _owner_id: str = Depends(require_course_ownership)) -> dict[str, Any]:
    return get_open_course_feedback(course_id)


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

class CourseFeedbackRuleUpdateRequest(BaseModel):
    status: str = Field(pattern="^(active|inactive|proposed)$")


class CourseFeedbackRuleMergeRequest(BaseModel):
    target_rule_id: str = Field(min_length=1, max_length=160)
    source_rule_ids: list[str] = Field(min_length=1, max_length=23)


@router.patch("/api/courses/{course_id}/course-feedback/rules/{rule_id}")
def update_feedback_rule(course_id: str, rule_id: str, payload: CourseFeedbackRuleUpdateRequest, _owner_id: str = Depends(require_course_ownership)) -> dict[str, Any]:
    try:
        return update_course_feedback_rule(course_id, rule_id, status=payload.status)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/api/courses/{course_id}/course-feedback/rules/merge")
def merge_feedback_rules(
    course_id: str,
    payload: CourseFeedbackRuleMergeRequest,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return merge_course_feedback_rules(course_id, payload.target_rule_id, payload.source_rule_ids)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete("/api/courses/{course_id}/course-feedback/rules/{rule_id}")
def delete_feedback_rule(course_id: str, rule_id: str, _owner_id: str = Depends(require_course_ownership)) -> dict[str, Any]:
    try:
        return delete_course_feedback_rule(course_id, rule_id)
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


class GlobalCourseFeedbackRefineRequest(BaseModel):
    extra_comment: str = Field(min_length=1, max_length=2000)


@router.post("/api/courses/{course_id}/course-feedback/{feedback_id}/global/refine")
def refine_global_feedback(
    course_id: str,
    feedback_id: str,
    payload: GlobalCourseFeedbackRefineRequest,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return refine_global_course_feedback(course_id, feedback_id, extra_comment=payload.extra_comment, model_json=_model_json)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


class GlobalCourseFeedbackApplyRequest(BaseModel):
    remember_preference: bool = True


@router.post("/api/courses/{course_id}/course-feedback/{feedback_id}/global/apply")
def apply_global_feedback(
    course_id: str,
    feedback_id: str,
    payload: GlobalCourseFeedbackApplyRequest = GlobalCourseFeedbackApplyRequest(),
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return apply_global_course_feedback(course_id, feedback_id, remember_preference=payload.remember_preference)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

