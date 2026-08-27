from __future__ import annotations

from pathlib import Path

import pytest

from app import study_service


def test_course_services_do_not_expose_a_default_course_id() -> None:
    assert not hasattr(study_service, "DEFAULT_COURSE_ID")
    assert not hasattr(study_service, "LEGACY_WORKSPACE_PATH")


def test_empty_workspace_requires_explicit_course() -> None:
    with pytest.raises(ValueError, match="必须提供课程信息"):
        study_service._empty_course_workspace([])


def test_save_workspace_rejects_missing_course_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(study_service, "COURSES_DATA_DIRECTORY", tmp_path / "courses")
    with pytest.raises(ValueError, match="必须提供 course_id"):
        study_service.save_workspace({"course": {}})
