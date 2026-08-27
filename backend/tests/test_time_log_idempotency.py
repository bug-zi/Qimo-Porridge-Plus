from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import study_service
from app.routers import practice


def _workspace() -> dict:
    return {
        "planStartDate": "2025-01-01",
        "tasks": [{"id": "task-1", "day": 1, "duration": 60, "status": "pending"}],
        "timeLog": [],
    }


def _patch_workspace(monkeypatch: pytest.MonkeyPatch, workspace: dict) -> list[dict]:
    saves: list[dict] = []
    monkeypatch.setattr(study_service, "load_workspace", lambda *args, **kwargs: workspace)
    monkeypatch.setattr(study_service, "save_workspace", lambda saved, *args, **kwargs: saves.append(saved))
    return saves


def test_record_time_reuses_existing_client_entry_id(monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _workspace()
    saves = _patch_workspace(monkeypatch, workspace)

    first = study_service.record_time(
        "course-1",
        task_id="task-1",
        minutes=25,
        target_date="2025-01-01",
        client_entry_id="client-entry-1",
    )
    duplicate = study_service.record_time(
        "course-1",
        task_id="task-1",
        minutes=50,
        target_date="2025-01-02",
        note="duplicate payload must be ignored",
        client_entry_id="client-entry-1",
    )

    assert first["entry"]["id"] == "client-entry-1"
    assert duplicate["entry"] is first["entry"]
    assert len(workspace["timeLog"]) == 1
    assert workspace["timeLog"][0]["minutes"] == 25
    assert duplicate["dailyProgress"] == study_service.build_daily_progress(workspace)
    assert len(saves) == 1


def test_record_time_appends_different_client_entry_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _workspace()
    saves = _patch_workspace(monkeypatch, workspace)

    for entry_id in ("client-entry-1", "client-entry-2"):
        study_service.record_time(
            "course-1",
            task_id=None,
            minutes=10,
            target_date="2025-01-01",
            client_entry_id=entry_id,
        )

    assert [entry["id"] for entry in workspace["timeLog"]] == ["client-entry-1", "client-entry-2"]
    assert len(saves) == 2


def test_record_time_without_client_id_keeps_generated_id(monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _workspace()
    saves = _patch_workspace(monkeypatch, workspace)

    result = study_service.record_time("course-1", task_id=None, minutes=15, target_date="2025-01-01")

    assert result["entry"]["id"].startswith("log-")
    assert workspace["timeLog"] == [result["entry"]]
    assert len(saves) == 1


def test_time_log_request_validation_and_route_forwarding(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        practice.TimeLogRequest(minutes=0)
    with pytest.raises(ValidationError):
        practice.TimeLogRequest(minutes=1441)
    with pytest.raises(ValidationError):
        practice.TimeLogRequest(minutes=1, client_entry_id="x" * 161)

    captured: dict = {}
    monkeypatch.setattr(practice, "record_time", lambda course_id, **kwargs: captured.update(course_id=course_id, **kwargs) or {})
    payload = practice.TimeLogRequest(minutes=20, client_entry_id="  client-entry-1  ")

    practice.add_course_time_log("course-1", payload, "owner-1")

    assert captured["client_entry_id"] == "client-entry-1"
    assert captured["minutes"] == 20
