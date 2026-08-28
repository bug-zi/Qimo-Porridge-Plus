from __future__ import annotations

from app.agents.answer_consistency import explanation_answer_index, reconcile_question_answer
from app import study_service


def conflicting_question() -> dict:
    return {
        "id": "self-test-4",
        "type": "single",
        "score": 5,
        "prompt": "50个进程一轮不超过1秒，时间片最大是多少？",
        "options": ["50毫秒", "20毫秒", "500毫秒", "2毫秒"],
        "answerIndex": 0,
        "explanation": (
            r"采用近似关系 \(T \approx QN\)，"
            r"\(Q_{max}=1\text{s}/50=0.02\text{s}=20\text{ms}\)。因此应选20毫秒。"
        ),
        "knowledgePointId": "kp-time-sharing",
        "source": "讲义",
    }


def test_explicit_explanation_conclusion_repairs_conflicting_answer_index() -> None:
    question = conflicting_question()

    assert explanation_answer_index(question) == 1
    assert reconcile_question_answer(question) is True
    assert question["answerIndex"] == 1
    assert reconcile_question_answer(question) is False


def test_mention_without_explicit_conclusion_does_not_override_answer() -> None:
    question = conflicting_question()
    question["explanation"] = "20毫秒与50毫秒都需要结合题目条件判断。"

    assert explanation_answer_index(question) is None
    assert reconcile_question_answer(question) is False
    assert question["answerIndex"] == 0


def test_letter_only_conclusion_is_ignored_after_option_shuffle() -> None:
    question = conflicting_question()
    question["explanation"] = "正确答案是B。"

    assert explanation_answer_index(question) is None


def test_submit_practice_answer_accepts_explanation_backed_answer(monkeypatch) -> None:
    question = conflicting_question()
    workspace = {
        "course": {"id": "course-test", "name": "操作系统"},
        "practiceQuestions": [question],
        "mockQuestions": [],
        "knowledgePoints": [{"id": "kp-time-sharing", "name": "分时系统", "mastery": 40, "weight": 100}],
        "tasks": [],
        "onboarding": {},
    }
    saved: list[dict] = []
    monkeypatch.setattr(study_service, "load_workspace", lambda _course_id: workspace)
    monkeypatch.setattr(study_service, "save_workspace", lambda item, _course_id: saved.append(item))
    monkeypatch.setattr(study_service, "record_learning_event", lambda *_args, **_kwargs: None)

    result = study_service.submit_practice_answer("self-test-4", 1, "主线学习", "course-test")

    assert result["correct"] is True
    assert result["mastery"] == 48
    assert result["generatedSimilarCount"] == 0
    assert question["answerIndex"] == 1
    assert workspace["practiceAnswers"]["self-test-4"]["correct"] is True
    assert workspace.get("wrongAnswers", []) == []
    assert saved == [workspace]
