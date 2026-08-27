"""Backend mock exam repair/fallback tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import study_service
from app.agents import workflow
from app.routers import practice


def planned_workspace(*, questions=None):
    return {
        "revision": 7,
        "course": {"id": "course-t", "name": "测试课程"},
        "onboarding": {"status": "planned", "examFormat": "单项选择题", "days": 2, "dailyHours": 1},
        "assessmentProfile": {"summary": "选择题考查核心概念", "questionTypes": ["单项选择题"]},
        "knowledgePoints": [
            {"id": "kp-a", "name": "核心概念", "summary": "理解定义、条件和应用。", "source": "讲义", "weight": 10}
        ],
        "tasks": [{"id": "task-a", "title": "核心概念", "knowledgePointId": "kp-a"}],
        "mockQuestions": list(questions or []),
    }


def test_workflow_mock_repair_falls_back_when_model_is_unavailable(monkeypatch):
    monkeypatch.setattr(workflow, "retrieve_material_context", lambda *a, **k: {"context": ""})

    def unavailable(*args, **kwargs):
        raise RuntimeError("model offline")

    result = workflow.repair_mock_questions("course-t", planned_workspace(), unavailable)

    assert result["source"] == "fallback"
    assert "model offline" in result["warning"]
    assert result["mockQuestions"]
    assert all(question["knowledgePointId"] == "kp-a" for question in result["mockQuestions"])
    assert all(len(question["options"]) == 4 for question in result["mockQuestions"])


def test_service_mock_repair_is_idempotent_without_force(monkeypatch):
    existing = [
        {
            "id": "existing",
            "type": "single",
            "questionType": "单项选择题",
            "score": 5,
            "prompt": "现有题目",
            "options": ["A", "B", "C", "D"],
            "answerIndex": 0,
            "explanation": "解析",
            "knowledgePointId": "kp-a",
            "source": "讲义",
        }
    ]
    workspace = planned_workspace(questions=existing)
    monkeypatch.setattr(study_service, "load_workspace", lambda *a, **k: workspace)
    monkeypatch.setattr(
        study_service,
        "repair_mock_questions",
        lambda *a, **k: pytest.fail("repair generator must not run for an existing exam"),
    )

    result = study_service.repair_course_mock_questions("course-t")

    assert result["repaired"] is False
    assert result["source"] == "existing"
    assert result["workspace"]["mockQuestions"] == existing


def test_service_mock_repair_replaces_corrupt_nonempty_exam(monkeypatch):
    workspace = planned_workspace(questions=[{"id": "broken", "type": "single", "options": []}])
    generated = [{"id": "generated", "knowledgePointId": "kp-a"}]
    monkeypatch.setattr(study_service, "load_workspace", lambda *a, **k: workspace)
    monkeypatch.setattr(study_service, "get_course_prompt", lambda *a, **k: "")
    monkeypatch.setattr(
        study_service,
        "repair_mock_questions",
        lambda *a, **k: {"mockQuestions": generated, "source": "fallback", "warning": "invalid model result"},
    )
    monkeypatch.setattr(study_service, "save_workspace", lambda *a, **k: None)

    result = study_service.repair_course_mock_questions("course-t")

    assert result["repaired"] is True
    assert result["workspace"]["mockQuestions"] == generated


def test_service_mock_repair_saves_with_revision_guard(monkeypatch):
    workspace = planned_workspace()
    generated = [{"id": "generated", "knowledgePointId": "kp-a"}]
    saved = {}
    monkeypatch.setattr(study_service, "load_workspace", lambda *a, **k: workspace)
    monkeypatch.setattr(study_service, "get_course_prompt", lambda *a, **k: "course rules")
    monkeypatch.setattr(
        study_service,
        "repair_mock_questions",
        lambda *a, **k: {"mockQuestions": generated, "source": "model", "warning": ""},
    )

    def capture_save(value, course_id, expected_revision=None):
        saved.update(value=value, course_id=course_id, expected_revision=expected_revision)

    monkeypatch.setattr(study_service, "save_workspace", capture_save)

    result = study_service.repair_course_mock_questions("course-t")

    assert result["repaired"] is True
    assert result["questionCount"] == 1
    assert saved["course_id"] == "course-t"
    assert saved["expected_revision"] == 7
    assert saved["value"]["mockQuestions"] == generated
    assert saved["value"]["mockQuestionsGenerationSource"] == "model"


def test_mock_repair_route_is_registered():
    paths = {(route.path, tuple(route.methods or ())) for route in practice.router.routes}
    assert any(path == "/api/courses/{course_id}/mock/repair" and "POST" in methods for path, methods in paths)
