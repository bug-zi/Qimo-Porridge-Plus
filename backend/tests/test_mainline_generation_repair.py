"""Regression tests for non-destructive mainline repair."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main, study_service
from app.agents import workflow
from app.routers import strategy as strategy_router
from app.routers.strategy import StrategyDocumentsUpdateRequest


def test_merge_repaired_content_preserves_plan_and_learning_records():
    completed_guide = {"examPoints": [{"id": "done-point"}]}
    base = {
        "planStartDate": "2026-01-27",
        "timeLogs": [{"id": "log-1", "taskId": "task-done", "minutes": 35}],
        "wrongAnswers": [{"id": "wrong-1"}],
        "tasks": [
            {
                "id": "task-done", "day": 1, "order": 1, "status": "completed",
                "progress": 100, "completedAt": "2026-01-28T10:00:00", "studyGuide": completed_guide,
            },
            {
                "id": "task-missing", "day": 9, "order": 9, "status": "in-progress",
                "progress": 40, "contentQualityWarning": "still generating",
            },
        ],
        "practiceQuestions": [{"id": "existing-q", "taskId": "task-done"}],
    }
    candidate = {
        "tasks": [
            {"id": "task-done", "status": "pending", "progress": 0, "studyGuide": {"replaced": True}},
            {"id": "task-missing", "status": "pending", "progress": 0, "studyGuide": {"examPoints": [{"id": "new"}]}},
            {"id": "unexpected-new-task", "studyGuide": {"unexpected": True}},
        ],
        "practiceQuestions": [
            {"id": "existing-q", "taskId": "task-done", "changed": True},
            {"id": "new-q", "taskId": "task-missing"},
        ],
    }

    merged = study_service._merge_repaired_content(base, candidate)

    assert [task["id"] for task in merged["tasks"]] == ["task-done", "task-missing"]
    assert merged["tasks"][0]["studyGuide"] is completed_guide
    assert merged["tasks"][0]["status"] == "completed"
    assert merged["tasks"][0]["progress"] == 100
    assert merged["tasks"][0]["completedAt"] == "2026-01-28T10:00:00"
    assert merged["tasks"][1]["status"] == "in-progress"
    assert merged["tasks"][1]["progress"] == 40
    assert merged["tasks"][1]["studyGuide"] == candidate["tasks"][1]["studyGuide"]
    assert "contentQualityWarning" not in merged["tasks"][1]
    assert merged["timeLogs"] == base["timeLogs"]
    assert merged["wrongAnswers"] == base["wrongAnswers"]
    assert merged["planStartDate"] == "2026-01-27"
    assert [question["id"] for question in merged["practiceQuestions"]] == ["existing-q", "new-q"]
    assert "changed" not in merged["practiceQuestions"][0]


def test_incremental_merge_accepts_final_mock_questions():
    base = {"tasks": [], "practiceQuestions": [], "mockQuestions": []}
    candidate = {"tasks": [], "practiceQuestions": [], "mockQuestions": [{"id": "mock-1"}]}
    merged = study_service._merge_repaired_content(base, candidate)
    assert merged["mockQuestions"] == [{"id": "mock-1"}]


def test_repair_request_defaults_safe_flag_to_false():
    normal = StrategyDocumentsUpdateRequest(
        review_plan="plan", course_prompt="prompt", review_plan_version=1, course_prompt_version=1
    )
    repair = StrategyDocumentsUpdateRequest(
        review_plan="plan", course_prompt="prompt", review_plan_version=1, course_prompt_version=1, repair_only=True
    )
    assert normal.repair_only is False
    assert repair.repair_only is True


def test_incremental_batch_selection_follows_mainline_and_skips_ready_or_orientation():
    tasks = [
        {"id": "orientation", "kind": "orientation", "day": 0, "order": 0},
        {"id": "later", "day": 2, "order": 3},
        {"id": "ready", "day": 1, "order": 1, "studyGuide": {}},
        {"id": "next", "day": 1, "order": 2},
        {"id": "last", "day": 3, "order": 4},
    ]
    assert [task["id"] for task in workflow._select_missing_lesson_tasks(tasks, 1)] == ["next"]
    assert [task["id"] for task in workflow._select_missing_lesson_tasks(tasks, 3)] == ["next", "later", "last"]
    assert [task["id"] for task in workflow._select_missing_lesson_tasks(tasks, None)] == ["next", "later", "last"]


def test_workflow_repair_parameter_is_available():
    assert "repair_only" in workflow.run_content_workflow.__annotations__


def test_repair_plan_validation_allows_existing_uneven_daily_schedule():
    candidate = {
        "assessmentProfile": {"summary": "existing"},
        "diagnostic": {"message": "existing"},
        "knowledgePoints": [{"id": "point-1"}],
        "tasks": [
            {
                "id": "day-4-task",
                "day": 4,
                "duration": 40,
                "knowledgePointId": "point-1",
                "title": "day 4",
                "description": "existing schedule",
                "source": "existing",
            },
            {
                "id": "day-5-task",
                "day": 5,
                "duration": 185,
                "knowledgePointId": "point-1",
                "title": "day 5",
                "description": "existing schedule",
                "source": "existing",
            },
        ],
    }

    normal_issues = workflow._plan_issues(candidate, expected_days=5, daily_minutes=120)
    repair_issues = workflow._plan_issues(
        candidate,
        expected_days=5,
        daily_minutes=120,
        validate_daily_budget=False,
    )

    assert any("第4天任务时长 40 分钟" in issue for issue in normal_issues)
    assert any("第5天任务时长 185 分钟" in issue for issue in normal_issues)
    assert repair_issues == []


def test_background_generation_waits_for_shared_content_lock(monkeypatch):
    received = {}

    def fake_approve(*args, **kwargs):
        received.update(kwargs)
        # handler 契约要求返回 workspace 用于汇报课程完成度：
        # orientation 任务不计入课时；1 课已完成、1 课待生成。
        return {
            "tasks": [
                {"id": "orientation", "kind": "orientation", "studyGuide": {}},
                {"id": "task-done", "studyGuide": {"examPoints": []}},
                {"id": "task-pending"},
            ]
        }

    monkeypatch.setattr(main, "approve_strategy_documents", fake_approve)
    result = main._approve_strategy_documents_job(
        "course-1",
        {
            "reviewPlan": "plan",
            "coursePrompt": "prompt",
            "reviewPlanVersion": 3,
            "coursePromptVersion": 4,
            "repairOnly": True,
        },
    )

    assert received["repair_only"] is True
    assert received["generation_mode"] == "all"
    assert received["lesson_limit"] is None
    assert received["continue_generation"] is False
    assert received["wait_for_generation_lock"] is True
    assert result["completedLessonCount"] == 1
    assert result["pendingLessonCount"] == 1
    assert result["contentComplete"] is False
    assert result["partial"] is True
    assert result["requestedLessonLimit"] is None


def test_background_generation_forwards_incremental_batch(monkeypatch):
    received = {}

    def fake_approve(*args, **kwargs):
        received.update(kwargs)
        # 同上：handler 需要读取 workspace 中的 tasks 汇报完成度。
        return {
            "tasks": [
                {"id": "task-1", "studyGuide": {"examPoints": []}},
                {"id": "task-2", "studyGuide": {"examPoints": []}},
                {"id": "task-3", "studyGuide": {"examPoints": []}},
            ]
        }

    monkeypatch.setattr(main, "approve_strategy_documents", fake_approve)
    result = main._approve_strategy_documents_job(
        "course-1",
        {
            "reviewPlan": "plan",
            "coursePrompt": "prompt",
            "reviewPlanVersion": 3,
            "coursePromptVersion": 4,
            "generationMode": "incremental",
            "lessonLimit": 3,
            "continueGeneration": True,
        },
    )

    assert received["generation_mode"] == "incremental"
    assert received["lesson_limit"] == 3
    assert received["continue_generation"] is True
    assert result["completedLessonCount"] == 3
    assert result["pendingLessonCount"] == 0
    assert result["contentComplete"] is True
    assert result["partial"] is False
    assert result["requestedLessonLimit"] == 3


def test_generation_request_validates_incremental_fields():
    request = StrategyDocumentsUpdateRequest(
        review_plan="plan", course_prompt="prompt", review_plan_version=1, course_prompt_version=1,
        generation_mode="incremental", lesson_limit=1, continue_generation=True,
    )
    assert request.generation_mode == "incremental"
    assert request.lesson_limit == 1
    assert request.continue_generation is True


def test_generation_enqueue_returns_authoritative_job(monkeypatch):
    monkeypatch.setattr(strategy_router, "enqueue_agent_job", lambda *args, **kwargs: "job-1")
    monkeypatch.setattr(strategy_router, "get_agent_job", lambda job_id: {
        "id": job_id, "courseId": "course-1", "status": "queued",
        "attempts": 0, "maxAttempts": 1, "progress": {},
    })
    payload = StrategyDocumentsUpdateRequest(
        review_plan="plan", course_prompt="prompt", review_plan_version=1, course_prompt_version=1,
        generation_mode="incremental", lesson_limit=1, continue_generation=True,
    )

    response = strategy_router.enqueue_course_strategy_approval("course-1", payload)

    assert response["jobId"] == "job-1"
    assert response["courseId"] == "course-1"
    assert response["job"]["maxAttempts"] == 1


def test_repair_does_not_rewrite_strategy_documents_or_increment_versions(monkeypatch):
    workspace = {
        "course": {"id": "course-1"},
        "onboarding": {"status": "planned"},
        "strategyDocuments": {
            "reviewPlan": {"version": 7},
            "coursePrompt": {"version": 9},
        },
        "tasks": [{"id": "missing"}],
        "planStartDate": "2026-01-01",
    }
    saved = []

    monkeypatch.setattr(study_service, "save_strategy_documents", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("repair must not rewrite documents")))
    monkeypatch.setattr(study_service, "load_workspace", lambda *args, **kwargs: workspace)
    monkeypatch.setattr(study_service, "scan_course_materials", lambda *args, **kwargs: [])
    monkeypatch.setattr(study_service, "sync_course_knowledge", lambda *args, **kwargs: None)
    monkeypatch.setattr(study_service, "retrieve_material_context", lambda *args, **kwargs: {"context": "evidence"})
    monkeypatch.setattr(
        study_service,
        "run_content_workflow",
        lambda *args, **kwargs: {
            "candidate": {"tasks": [{"id": "missing", "studyGuide": {"examPoints": []}}]},
            "runId": "run-repair",
            "reviewReport": {"passed": True},
        },
    )
    monkeypatch.setattr(study_service, "_merge_repaired_content", lambda latest, candidate: latest)
    monkeypatch.setattr(study_service, "save_workspace", lambda value, *args, **kwargs: saved.append(value))
    monkeypatch.setattr(study_service, "enqueue_agent_job", lambda *args, **kwargs: "job-glossary")

    result = study_service.approve_strategy_documents(
        "course-1",
        "plan",
        "prompt",
        expected_review_plan_version=7,
        expected_course_prompt_version=9,
        repair_only=True,
    )

    assert result["strategyDocuments"]["reviewPlan"]["version"] == 7
    assert result["strategyDocuments"]["coursePrompt"]["version"] == 9
    assert result["strategyDocuments"]["lastAgentRunId"] == "run-repair"
    assert saved
