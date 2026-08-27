from __future__ import annotations

import hashlib
import json

from app.agents import checkpoint_contracts as contracts
from app.agents.lesson_generation import LessonBuilder, LessonRuntimeDeps


def legacy_digest(payload) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def test_content_plan_signature_excludes_diagnostic_results() -> None:
    plan_payload = {
        "formulaOutputContractVersion": 1,
        "course": {"id": "课程-1", "name": "测试"},
        "onboarding": {"days": 3, "dailyHours": 2},
        "reviewPlan": "计划",
        "coursePrompt": "规则",
    }
    plan = contracts.content_plan_signature(
        course=plan_payload["course"], onboarding=plan_payload["onboarding"],
        review_plan="计划", course_prompt="规则",
    )
    assert plan == legacy_digest(plan_payload)


def test_checkpoint_signatures_match_historical_payload_contracts() -> None:

    lesson_payload = {
        "formulaOutputContractVersion": 1,
        "lessonContentContractVersion": 4,
        "styleContract": {"id": "story", "version": 3},
        "task": {"id": "task-1", "day": 1, "order": 1},
        "reviewPlan": "计划",
        "coursePrompt": "规则",
    }
    lesson = contracts.lesson_content_signature(
        style_contract=lesson_payload["styleContract"], task=lesson_payload["task"],
        review_plan="计划", course_prompt="规则",
    )
    assert lesson == legacy_digest(lesson_payload)
    assert lesson == "c9d6dd49de221b6858371fee59c5bf26761ea61dcc9115bca0dac8cc21d6dc7b"
    assert contracts.lesson_guide_signature(lesson) == "ab40983fd6a1c3a574abf16804628897dc0fb0bd60ccf9429c62c0888cef6548"
    assert contracts.lesson_questions_signature(
        lesson_signature=lesson, exam_points=[{"id": "ep-1", "title": "考点"}]
    ) == "c312e1e6db55d6aa17c05d862f7d9f74947c1bf3fe550d4f6c670bb308ee0d05"

    assert contracts.mock_questions_signature(
        onboarding={"days": 3}, knowledge_points=[{"id": "kp-1"}],
        task_plan=[{"id": "task-1"}], review_plan="计划", course_prompt="规则",
    ) == "c823654a5b2ba2756cf63df5667b6675a226e1b5f122f72ceccdb7a4f2b54ff8"
    assert contracts.orientation_guide_signature(
        modules=[{"id": "m-1"}], knowledge_points=[{"id": "kp-1"}],
        review_plan="计划", days=3,
    ) == "13593334fb08ea26cfcc0857ec89bbfff277f6f93c163f0e7fc80be45414cf09"


def test_lesson_builder_reuses_valid_legacy_checkpoint_without_retrieval(monkeypatch) -> None:
    task = {"id": "task-1", "day": 1, "order": 1, "knowledgePointId": "kp-1"}
    guide = {
        "examPoints": [{
            "id": "ep-1", "title": "考点", "explanation": "实质讲解",
            "sourceRefs": ["资料"], "teachingMode": "concept", "formulas": [],
        }],
        "workedExamples": [{
            "id": "ex-1", "problem": "完整题干", "analysis": "完整分析",
            "answer": "明确答案", "source": "资料", "steps": ["步骤"],
            "examPointIds": ["ep-1"],
        }],
        "selfTestQuestionIds": ["task-1-q1"],
    }
    questions = [{
        "id": "task-1-q1", "taskId": "task-1", "examPointIds": ["ep-1"],
        "type": "single", "prompt": "完整题干", "explanation": "详细解析",
        "options": ["A", "B"], "answerIndex": 0,
    }]
    signature = contracts.lesson_content_signature(
        style_contract={"id": "standard"}, task=task, review_plan="计划", course_prompt="规则"
    )

    def latest(_course_id, artifact_type):
        assert artifact_type == "lesson_content_checkpoint:task-1"
        return {"content": {"signature": signature, "studyGuide": guide, "practiceQuestions": questions}}

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("valid legacy checkpoint should bypass retrieval/model/save")

    builder = LessonBuilder(
        course_id="course-1", workspace={"course": {}, "onboarding": {}}, review_plan="计划",
        course_prompt="规则", evidence_context="", model_json=should_not_run, run_id="run-1",
        content_style="standard", style_contract={"id": "standard"}, strong_feedback_directives=[],
        point_by_id={"kp-1": {"id": "kp-1"}}, ordered_lessons=[task],
        lesson_index_by_id={"task-1": 0}, check_cancelled=lambda: None,
        deps=LessonRuntimeDeps(
            get_latest_artifact=latest, save_artifact=should_not_run,
            retrieve_material_context=should_not_run, shuffle_single_choice_options=lambda item: item,
        ),
    )
    task_id, reused_guide, reused_questions, report, degraded = builder.build(task)
    assert task_id == "task-1"
    assert reused_guide is guide
    assert reused_questions[0]["id"] == "task-1-q1"
    assert report.passed is True
    assert degraded is False
