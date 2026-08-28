from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app, initialize_database
from app.auth_service import initialize_auth_database
from app.routers import course_feedback as feedback_router
from app.routers import deps
from app.tenancy import claim_legacy_courses, ensure_owner_columns


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(deps, "DATA_DIRECTORY", data_dir)
    monkeypatch.setattr(deps, "DATABASE_PATH", data_dir / "exam_booster.db")
    # The workspace facade reads these shared path values.
    from app import paths as app_paths
    monkeypatch.setattr(app_paths, "DATA_DIRECTORY", data_dir)
    monkeypatch.setattr(app_paths, "COURSES_DATA_DIRECTORY", data_dir / "courses")
    monkeypatch.setattr(app_paths, "MATERIAL_CACHE_DIRECTORY", data_dir / "material_cache")
    initialize_database()
    initialize_auth_database()
    ensure_owner_columns()
    claim_legacy_courses()
    with TestClient(app) as test_client:
        yield test_client


def register(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "display_name": email.split("@")[0], "password": "Aa123456!"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_course(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/courses",
        headers=headers,
        json={"name": "反馈路由契约测试课", "exam_date": "2027-01-01", "target_score": 85, "daily_hours": 2},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_feedback_routes_require_authentication_and_hide_foreign_courses(client: TestClient):
    unauthenticated = client.get("/api/courses/course-missing/course-feedback")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["detail"] == "未登录或缺少访问令牌"

    alice = register(client, "feedback-router-alice@example.com")
    bob = register(client, "feedback-router-bob@example.com")
    course_id = create_course(client, alice)
    assert client.get(f"/api/courses/{course_id}/course-feedback", headers=bob).status_code == 404
    assert client.get(f"/api/courses/{course_id}/course-feedback/rules", headers=bob).status_code == 404


def test_feedback_submit_retry_abandon_and_apply_response_shapes(client, monkeypatch):
    owner = register(client, "feedback-router-lifecycle@example.com")
    course_id = create_course(client, owner)
    calls: list[str] = []

    def fake_model(_system: str, user: str, _schema: str) -> dict[str, Any]:
        calls.append(user)
        if "ruleCandidate" in _system:
            return {"problemTypes": ["too_verbose"], "diagnosis": "过长", "suggestedRewrite": "更短", "ruleCandidate": {"type": "tone", "title": "简洁", "description": "使用短句", "badPattern": "冗长", "preferredPattern": "短句"}}
        return {"rewrittenText": "改写后的正文", "rationale": "更清晰", "safetyNotes": ["保留事实"], "replaceable": True}

    monkeypatch.setattr(feedback_router, "_model_json", fake_model)
    submitted = client.post(
        f"/api/courses/{course_id}/course-feedback",
        headers=owner,
        json={"selected_text": "原始正文", "user_comment": "请改短", "context": {"taskId": "task-1", "field": "concept.body"}},
    )
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert {"feedbackId", "status", "rewriteProposal", "proposalStatus", "feedbackSaved"} <= body.keys()
    feedback_id = body["feedbackId"]
    assert body["status"] == "awaiting_confirmation"
    assert body["rewriteProposal"]["rewrittenText"] == "改写后的正文"

    retried = client.post(f"/api/courses/{course_id}/course-feedback/{feedback_id}/proposal/retry", headers=owner)
    assert retried.status_code == 200, retried.text
    assert {"feedbackId", "status", "rewriteProposal", "proposalStatus", "canRetryProposal"} <= retried.json().keys()

    abandoned = client.post(f"/api/courses/{course_id}/course-feedback/{feedback_id}/abandon", headers=owner)
    assert abandoned.status_code == 200, abandoned.text
    assert abandoned.json() == {"feedbackId": feedback_id, "status": "abandoned", "message": "已放弃本次修改建议。"}

    rejected = client.post(
        f"/api/courses/{course_id}/course-feedback/{feedback_id}/rewrite/apply",
        headers=owner,
        json={},
    )
    assert rejected.status_code == 422
    assert "反馈会话已结束" in rejected.json()["detail"]
    assert calls


def test_feedback_missing_and_validation_errors_have_distinct_statuses(client):
    owner = register(client, "feedback-router-validation@example.com")
    course_id = create_course(client, owner)
    missing = client.post(f"/api/courses/{course_id}/course-feedback/missing/abandon", headers=owner)
    assert missing.status_code == 422
    assert missing.json()["detail"] == "反馈记录不存在"

    invalid = client.post(
        f"/api/courses/{course_id}/course-feedback",
        headers=owner,
        json={"selected_text": "", "user_comment": "", "context": {}},
    )
    assert invalid.status_code == 422

    bad_rule = client.patch(
        f"/api/courses/{course_id}/course-feedback/rules/rule-1",
        headers=owner,
        json={"status": "invalid"},
    )
    assert bad_rule.status_code == 422


def test_apply_maps_revision_conflict_to_409_and_preserves_server_shape(client, monkeypatch):
    owner = register(client, "feedback-router-conflict@example.com")
    course_id = create_course(client, owner)

    def conflict(*_args, **_kwargs):
        raise RuntimeError("学习空间已被其他操作更新，请刷新后重试")

    monkeypatch.setattr(feedback_router, "apply_course_feedback_rewrite", conflict)
    response = client.post(
        f"/api/courses/{course_id}/course-feedback/feedback-1/rewrite/apply",
        headers=owner,
        json={"expected_revision": 3},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "学习空间已被其他操作更新，请刷新后重试"


def test_rewrite_partial_failure_is_explicit_not_success(client, monkeypatch):
    owner = register(client, "feedback-router-failure@example.com")
    course_id = create_course(client, owner)

    def failed(*_args, **_kwargs):
        return {"feedbackId": "feedback-1", "status": "analyzed", "feedbackSaved": True, "proposalStatus": "failed", "rewriteError": "上游不可用", "canRetryProposal": True}

    monkeypatch.setattr(feedback_router, "submit_course_feedback_with_rewrite", failed)
    response = client.post(
        f"/api/courses/{course_id}/course-feedback",
        headers=owner,
        json={"selected_text": "正文", "user_comment": "改写", "context": {}},
    )
    assert response.status_code == 200
    assert response.json()["proposalStatus"] == "failed"
    assert response.json()["rewriteError"] == "上游不可用"
    assert response.json()["canRetryProposal"] is True
