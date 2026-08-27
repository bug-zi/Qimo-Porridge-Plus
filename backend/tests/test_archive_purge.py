from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routers import deps


def initialize_test_data(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    database_path = data_dir / "exam_booster.db"
    courses_dir = data_dir / "courses"
    data_dir.mkdir(parents=True)
    monkeypatch.setattr(deps, "DATA_DIRECTORY", data_dir)
    monkeypatch.setattr(deps, "DATABASE_PATH", database_path)
    with deps.get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE archived_items (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, item_type TEXT NOT NULL,
                entity_id TEXT NOT NULL, title TEXT NOT NULL, course_id TEXT,
                course_name TEXT, payload TEXT NOT NULL, deleted_at TEXT NOT NULL,
                purge_after TEXT NOT NULL
            );
            CREATE TABLE courses (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL);
            CREATE TABLE plan_tasks (id TEXT PRIMARY KEY, course_id TEXT NOT NULL);
            """
        )
    return database_path, courses_dir


def seed_archived_course(database_path: Path, courses_dir: Path, *, expired: bool) -> tuple[str, str]:
    archive_id = "archive-course-test"
    course_id = "course-to-purge"
    course_dir = courses_dir / course_id
    course_dir.mkdir(parents=True)
    (course_dir / "workspace.json").write_text('{"course": {"id": "course-to-purge"}}', encoding="utf-8")
    now = datetime.now()
    purge_after = now - timedelta(seconds=1) if expired else now + timedelta(days=7)
    with sqlite3.connect(database_path) as connection:
        connection.execute("INSERT INTO courses (id, owner_id) VALUES (?, ?)", (course_id, "owner-a"))
        connection.execute("INSERT INTO plan_tasks (id, course_id) VALUES (?, ?)", ("task-1", course_id))
        connection.execute(
            "INSERT INTO archived_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (archive_id, "owner-a", "course", course_id, "测试课", course_id, "测试课", json.dumps({}), now.isoformat(timespec="seconds"), purge_after.isoformat(timespec="seconds")),
        )
    return archive_id, course_id


def test_manual_permanent_delete_removes_archive_database_and_course_directory(tmp_path, monkeypatch):
    database_path, courses_dir = initialize_test_data(tmp_path, monkeypatch)
    archive_id, course_id = seed_archived_course(database_path, courses_dir, expired=False)

    with deps.get_connection() as connection:
        assert deps.permanently_delete_archive_item(connection, archive_id, "owner-a") is True
        assert connection.execute("SELECT 1 FROM archived_items WHERE id = ?", (archive_id,)).fetchone() is None
        assert connection.execute("SELECT 1 FROM courses WHERE id = ?", (course_id,)).fetchone() is None
        assert connection.execute("SELECT 1 FROM plan_tasks WHERE course_id = ?", (course_id,)).fetchone() is None
    assert not (courses_dir / course_id).exists()


def test_expired_archive_purge_removes_course_data_not_only_archive_row(tmp_path, monkeypatch):
    database_path, courses_dir = initialize_test_data(tmp_path, monkeypatch)
    archive_id, course_id = seed_archived_course(database_path, courses_dir, expired=True)

    with deps.get_connection() as connection:
        assert deps.purge_expired_archive_items(connection) == 1
        assert connection.execute("SELECT 1 FROM archived_items WHERE id = ?", (archive_id,)).fetchone() is None
        assert connection.execute("SELECT 1 FROM courses WHERE id = ?", (course_id,)).fetchone() is None
    assert not (courses_dir / course_id).exists()
