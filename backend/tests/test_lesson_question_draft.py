from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from app.agents.content_prompts import (
    LESSON_CONTENT_PROMPT,
    LESSON_PRACTICE_PATCH_PROMPT,
    LESSON_PRACTICE_PROMPT,
)
from app.agents.lesson_generation import LessonBuilder, LessonRuntimeDeps


def _valid_guide() -> dict[str, Any]:
    return {
        "examPoints": [
            {"id": "ep-1", "title": "考点一", "explanation": "实质讲解", "sourceRefs": ["资料"], "teachingMode": "concept", "formulas": []},
            {"id": "ep-2", "title": "考点二", "explanation": "实质讲解", "sourceRefs": ["资料"], "teachingMode": "concept", "formulas": []},
        ],
        "workedExamples": [{
            "id": "ex-1", "problem": "完整题干", "analysis": "完整分析",
            "answer": "明确答案", "source": "资料", "steps": ["步骤"],
            "examPointIds": ["ep-1"],
        }],
    }


def _question(question_id: str, point_ids: list[str]) -> dict[str, Any]:
    return {
        "id": question_id, "taskId": "task-1", "examPointIds": point_ids,
        "type": "single", "prompt": "完整题干", "explanation": "详细解析",
        "options": ["A", "B"], "answerIndex": 0,
    }


def _builder(model_json, saved: list[tuple[str, dict[str, Any]]]) -> LessonBuilder:
    task = {"id": "task-1", "day": 1, "order": 1, "knowledgePointId": "kp-1"}
    builder = LessonBuilder(
        course_id="course-1", workspace={"course": {}, "onboarding": {}}, review_plan="计划",
        course_prompt="规则", evidence_context="", model_json=model_json, run_id="run-1",
        content_style="standard", style_contract={"id": "standard"}, strong_feedback_directives=[],
        point_by_id={"kp-1": {"id": "kp-1"}}, ordered_lessons=[task],
        lesson_index_by_id={"task-1": 0}, check_cancelled=lambda: None,
        deps=LessonRuntimeDeps(
            get_latest_artifact=lambda *_args, **_kwargs: None,
            save_artifact=lambda _course_id, artifact_type, content, **_kwargs: saved.append((artifact_type, content)),
            retrieve_material_context=lambda *_args, **_kwargs: {"context": ""},
            shuffle_single_choice_options=lambda item: item,
        ),
    )
    return builder


def test_no_question_checkpoint_generates_full_draft_before_any_patch() -> None:
    """回归：自测检查点缺失时曾直接拿空初稿进 patch 分支（初稿生成调用在重构中被删），
    模型用 add_question 补的题不带 examPointIds，覆盖校验只认该字段，
    导致"补了题但考点仍全部未覆盖"的循环失败（现场：task-d3-03）。"""
    saved: list[tuple[str, dict[str, Any]]] = []
    prompts: list[str] = []

    def model_json(prompt: str, payload_json: str, _course_prompt: str) -> dict[str, Any]:
        prompts.append(prompt)
        if prompt == LESSON_CONTENT_PROMPT:
            return {"studyGuide": _valid_guide()}
        # 自测初稿完整生成，覆盖全部考点 → 不应再触发 patch
        return {"practiceQuestions": [_question("q1", ["ep-1", "ep-2"])]}

    task_id, guide, questions, report, degraded = _builder(model_json, saved).build(
        {"id": "task-1", "day": 1, "order": 1, "knowledgePointId": "kp-1"}
    )
    assert task_id == "task-1"
    assert prompts == [LESSON_CONTENT_PROMPT, LESSON_PRACTICE_PROMPT]
    assert LESSON_PRACTICE_PATCH_PROMPT not in prompts
    assert questions[0]["id"] == "task-1-q1"
    assert guide["selfTestQuestionIds"] == ["task-1-q1"]
    assert report.passed is True
    assert degraded is False
    assert any(artifact_type == "lesson_questions_checkpoint:task-1" for artifact_type, _ in saved)


def test_patch_receives_real_draft_and_records_input_issues_separately() -> None:
    """回归 1：patch 的输入必须是有内容的 practiceQuestionsDraft，不是空数组。
    回归 2：lesson_questions_patch artifact 的 inputReviewIssues 曾把修复后剩余问题
    误存成输入问题（两者完全相同），误导诊断。"""
    saved: list[tuple[str, dict[str, Any]]] = []
    patch_payloads: list[dict[str, Any]] = []

    def model_json(prompt: str, payload_json: str, _course_prompt: str) -> dict[str, Any]:
        if prompt == LESSON_CONTENT_PROMPT:
            return {"studyGuide": _valid_guide()}
        if prompt == LESSON_PRACTICE_PROMPT:
            # 初稿只覆盖 ep-1，ep-2 缺失 → blocking
            return {"practiceQuestions": [_question("q1", ["ep-1"])]}
        assert prompt == LESSON_PRACTICE_PATCH_PROMPT
        patch_payloads.append(json.loads(payload_json))
        return {"patches": [{"op": "add_question", "question": _question("q2", ["ep-2"])}]}

    task_id, _guide, questions, _report, _degraded = _builder(model_json, saved).build(
        {"id": "task-1", "day": 1, "order": 1, "knowledgePointId": "kp-1"}
    )
    assert task_id == "task-1"
    # patch 收到的是真实初稿（含 q1），不是空数组
    assert patch_payloads, "缺考点时应触发自测 patch"
    draft_ids = [str(q.get("id")) for q in patch_payloads[0]["practiceQuestionsDraft"]]
    assert draft_ids == ["task-1-q1"]
    # 补题带 examPointIds 后覆盖校验应通过
    assert [q["id"] for q in questions] == ["task-1-q1", "task-1-q2"]
    patch_artifacts = [content for artifact_type, content in saved if artifact_type == "lesson_questions_patch:task-1"]
    assert patch_artifacts, "应保存 lesson_questions_patch artifact"
    assert patch_artifacts[0]["inputReviewIssues"] == ["任务 task-1 的考点 ep-2 没有被自测题覆盖"]
    assert patch_artifacts[0]["remainingIssues"] == []
