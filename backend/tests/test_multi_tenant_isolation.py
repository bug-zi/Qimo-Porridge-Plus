r"""多租户隔离回归测试（阶段2-4）。

覆盖课程列表、课程级路由、归档列表/恢复与用户自画像按 owner 隔离。
运行：cd backend && .venv\Scripts\python -m pytest tests/test_multi_tenant_isolation.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

from app import study_service
from app.auth_service import initialize_auth_database
from app.main import app, initialize_database
from app.routers import deps
from app.tenancy import claim_legacy_courses, ensure_owner_columns


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Run the FastAPI app against an isolated SQLite/data directory."""
    data_dir = tmp_path / "data"
    db_path = data_dir / "exam_booster.db"
    courses_dir = data_dir / "courses"

    monkeypatch.setattr(deps, "DATA_DIRECTORY", data_dir)
    monkeypatch.setattr(deps, "DATABASE_PATH", db_path)
    monkeypatch.setattr(study_service, "DATA_DIRECTORY", data_dir)
    monkeypatch.setattr(study_service, "COURSES_DATA_DIRECTORY", courses_dir)
    monkeypatch.setattr(study_service, "MATERIAL_CACHE_DIRECTORY", data_dir / "material_cache")

    initialize_database()
    initialize_auth_database()
    ensure_owner_columns()
    claim_legacy_courses()

    with TestClient(app) as test_client:
        yield test_client


def register(client: TestClient, email: str, display_name: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "display_name": display_name, "password": "Aa123456!"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {
        "user_id": body["user"]["id"],
        "access_token": body["access_token"],
        "authorization": f"Bearer {body['access_token']}",
    }


def create_course(client: TestClient, auth: dict[str, str], name: str) -> str:
    response = client.post(
        "/api/courses",
        headers={"Authorization": auth["authorization"]},
        json={"name": name, "exam_date": "2026-07-01", "target_score": 85, "daily_hours": 2},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_courses_are_listed_and_accessed_only_by_owner(client: TestClient):
    alice = register(client, "tenant-alice@example.com", "Alice")
    bob = register(client, "tenant-bob@example.com", "Bob")

    alice_course_id = create_course(client, alice, "Alice 专属课")
    bob_course_id = create_course(client, bob, "Bob 专属课")

    alice_courses = client.get("/api/courses", headers={"Authorization": alice["authorization"]}).json()
    bob_courses = client.get("/api/courses", headers={"Authorization": bob["authorization"]}).json()

    assert {course["id"] for course in alice_courses} == {alice_course_id}
    assert {course["id"] for course in bob_courses} == {bob_course_id}

    assert client.get(f"/api/courses/{alice_course_id}/workspace", headers={"Authorization": alice["authorization"]}).status_code == 200
    assert client.get(f"/api/courses/{alice_course_id}/workspace", headers={"Authorization": bob["authorization"]}).status_code == 404
    assert client.get(f"/api/courses/{bob_course_id}/plan", headers={"Authorization": alice["authorization"]}).status_code == 404


def test_archive_list_and_restore_are_owner_scoped(client: TestClient):
    alice = register(client, "archive-alice@example.com", "Archive Alice")
    bob = register(client, "archive-bob@example.com", "Archive Bob")
    alice_course_id = create_course(client, alice, "Alice 待归档课")

    archive_response = client.delete(
        f"/api/courses/{alice_course_id}",
        headers={"Authorization": alice["authorization"]},
    )
    assert archive_response.status_code == 200, archive_response.text
    archive_id = archive_response.json()["id"]

    alice_archive = client.get("/api/archive", headers={"Authorization": alice["authorization"]}).json()
    bob_archive = client.get("/api/archive", headers={"Authorization": bob["authorization"]}).json()
    assert [item["id"] for item in alice_archive] == [archive_id]
    assert bob_archive == []

    assert client.post(f"/api/archive/{archive_id}/restore", headers={"Authorization": bob["authorization"]}).status_code == 404

    restore_response = client.post(f"/api/archive/{archive_id}/restore", headers={"Authorization": alice["authorization"]})
    assert restore_response.status_code == 200, restore_response.text
    assert restore_response.json()["course"]["id"] == alice_course_id

    alice_courses = client.get("/api/courses", headers={"Authorization": alice["authorization"]}).json()
    assert {course["id"] for course in alice_courses} == {alice_course_id}


def test_user_profile_prompt_is_owner_scoped(client: TestClient):
    alice = register(client, "profile-alice@example.com", "Profile Alice")
    bob = register(client, "profile-bob@example.com", "Profile Bob")

    alice_update = client.put(
        "/api/user-profile",
        headers={"Authorization": alice["authorization"]},
        json={"content": "Alice only memory"},
    )
    assert alice_update.status_code == 200, alice_update.text

    bob_update = client.put(
        "/api/user-profile",
        headers={"Authorization": bob["authorization"]},
        json={"content": "Bob only memory"},
    )
    assert bob_update.status_code == 200, bob_update.text

    alice_profile = client.get("/api/user-profile", headers={"Authorization": alice["authorization"]}).json()
    bob_profile = client.get("/api/user-profile", headers={"Authorization": bob["authorization"]}).json()

    assert alice_profile["content"] == "Alice only memory"
    assert bob_profile["content"] == "Bob only memory"
