from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_feedback_cors_preflight_from_gui_needs_no_bearer_token() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/api/courses/course-1/course-feedback",
            headers={
                "Origin": "http://127.0.0.1:3500",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3500"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_feedback_post_still_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/courses/course-1/course-feedback",
            json={"selected_text": "text", "user_comment": "comment", "context": {}},
            headers={"Origin": "http://127.0.0.1:3500"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "未登录或缺少访问令牌"
