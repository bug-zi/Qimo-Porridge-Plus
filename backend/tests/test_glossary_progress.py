from __future__ import annotations

import sqlite3

from app import agent_runtime


def test_glossary_refresh_state_migrates_progress_columns(tmp_path, monkeypatch):
    database_path = tmp_path / "agent-runtime.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE glossary_refresh_state (
                course_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'idle',
                content_signature TEXT NOT NULL DEFAULT '',
                terms_total INTEGER NOT NULL DEFAULT 0,
                terms_active INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                last_refreshed_at TEXT NOT NULL DEFAULT ''
            )
            """
        )

    monkeypatch.setattr(agent_runtime, "DATABASE_PATH", database_path)
    monkeypatch.setattr(agent_runtime, "DATA_DIRECTORY", tmp_path)
    agent_runtime.initialize_agent_database()

    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(glossary_refresh_state)")}

    assert {"phase", "candidates_total", "terms_completed", "started_at", "progress_updated_at"} <= columns
    state = agent_runtime.get_glossary_refresh_state("course-progress")
    assert state["phase"] == "idle"
    assert state["candidatesTotal"] == 0
    assert state["termsCompleted"] == 0


def test_glossary_progress_state_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_runtime, "DATABASE_PATH", tmp_path / "agent-runtime.db")
    monkeypatch.setattr(agent_runtime, "DATA_DIRECTORY", tmp_path)
    agent_runtime.initialize_agent_database()

    state = agent_runtime.save_glossary_refresh_state(
        "course-progress",
        status="generating",
        phase="composing",
        candidates_total=30,
        terms_completed=10,
        terms_total=10,
        terms_active=10,
        started_at="2026-08-23T12:00:00",
        progress_updated_at="2026-08-23T12:01:00",
    )

    assert state["status"] == "generating"
    assert state["phase"] == "composing"
    assert state["candidatesTotal"] == 30
    assert state["termsCompleted"] == 10
    assert state["termsActive"] == 10
