from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..agent_runtime import enqueue_agent_job
from ..study_service import (
    clear_mock_result,
    clear_practice_answer,
    delete_time_entry,
    load_workspace,
    mark_strategy_maintenance_pending,
    record_time,
    save_workspace,
    submit_mock_answers,
    submit_practice_answer,
    submit_wrong_answer_retry,
)
from .deps import WrongAnswerArchiveResponse, create_archive_item, get_connection

router = APIRouter()


class PracticeAnswerRequest(BaseModel):
    question_id: str = Field(min_length=1, max_length=120)
    answer_index: int = Field(ge=0)
    mode: Literal["主线学习", "刷题练习"] = "刷题练习"


class WrongAnswerRetryRequest(BaseModel):
    answer_index: int = Field(ge=0)


class MockSubmitRequest(BaseModel):
    answers: dict[str, Any]


class TimeLogRequest(BaseModel):
    task_id: str = Field(default="", max_length=120)
    minutes: int = Field(ge=1, le=1440)
    target_date: str = Field(default="", max_length=10)
    note: str = Field(default="", max_length=200)


@router.post("/api/courses/{course_id}/time-log")
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


@router.delete("/api/courses/{course_id}/time-log/{entry_id}")
def remove_course_time_log(course_id: str, entry_id: str) -> dict[str, Any]:
    try:
        return delete_time_entry(course_id, entry_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/api/courses/{course_id}/practice/answer")
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


@router.delete(
    "/api/courses/{course_id}/wrong-answers/{wrong_answer_id}",
    response_model=WrongAnswerArchiveResponse,
)
def archive_course_wrong_answer(course_id: str, wrong_answer_id: str) -> WrongAnswerArchiveResponse:
    return _archive_course_wrong_answer(course_id, wrong_answer_id)


@router.post("/api/courses/{course_id}/wrong-answers/{wrong_answer_id}/retry")
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


@router.post("/api/courses/{course_id}/mock/submit")
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


@router.delete("/api/courses/{course_id}/practice/answers/{question_id}")
def clear_course_practice_answer(course_id: str, question_id: str) -> dict[str, Any]:
    try:
        return clear_practice_answer(question_id, course_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/api/courses/{course_id}/mock/result")
def clear_course_mock_result(course_id: str) -> dict[str, Any]:
    try:
        return clear_mock_result(course_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
