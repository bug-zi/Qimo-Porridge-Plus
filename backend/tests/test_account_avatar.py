from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

from app.auth_service import initialize_auth_database
from app.main import app, initialize_database
from app.routers import deps


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(deps, "DATA_DIRECTORY", data_dir)
    monkeypatch.setattr(deps, "DATABASE_PATH", data_dir / "exam_booster.db")
    initialize_database()
    initialize_auth_database()
    with TestClient(app) as test_client:
        yield test_client


def register(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/register",
        json={"email": "avatar@example.com", "display_name": "Avatar", "password": "Aa123456!"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_avatar_upload_is_persisted_in_database(client: TestClient):
    headers = register(client)
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")

    uploaded = client.post(
        "/api/account-profile/avatar",
        headers=headers,
        files={"avatar": ("avatar.png", png, "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["avatar_url"] == f"data:image/png;base64,{base64.b64encode(png).decode('ascii')}"

    profile = client.get("/api/account-profile", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["avatar_url"] == uploaded.json()["avatar_url"]

    updated = client.put(
        "/api/account-profile",
        headers=headers,
        json={"display_name": "Renamed", "gender": "", "age": None, "signature": ""},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["avatar_url"] == uploaded.json()["avatar_url"]

    deleted = client.delete("/api/account-profile/avatar", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["avatar_url"] == ""


def test_avatar_upload_rejects_non_image_and_oversize(client: TestClient):
    headers = register(client)
    wrong_type = client.post(
        "/api/account-profile/avatar",
        headers=headers,
        files={"avatar": ("avatar.txt", b"not an image", "text/plain")},
    )
    assert wrong_type.status_code == 422

    oversize = client.post(
        "/api/account-profile/avatar",
        headers=headers,
        files={"avatar": ("avatar.png", b"\x89PNG\r\n\x1a\n" + b"0" * (2 * 1024 * 1024), "image/png")},
    )
    assert oversize.status_code == 413
