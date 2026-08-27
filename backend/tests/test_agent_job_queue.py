"""Agent job queue priority, deduplication and lease tests."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import agent_runtime


def _use_temp_database(monkeypatch, tmp_path):
    database = tmp_path / "agent.db"
    monkeypatch.setattr(agent_runtime, "DATABASE_PATH", database)
    agent_runtime.initialize_agent_database()
    return database


def test_enqueue_deduplicates_active_jobs_by_course_and_type(monkeypatch, tmp_path):
    _use_temp_database(monkeypatch, tmp_path)
    first = agent_runtime.enqueue_agent_job("course-1", "rebalance_daily_plan", {"event": "first"})
    second = agent_runtime.enqueue_agent_job("course-1", "rebalance_daily_plan", {"event": "poll again"})
    other_course = agent_runtime.enqueue_agent_job("course-2", "rebalance_daily_plan", {"event": "first"})

    assert second == first
    assert other_course != first


def test_generation_job_bypasses_maintenance_backlog(monkeypatch, tmp_path):
    _use_temp_database(monkeypatch, tmp_path)
    maintenance = agent_runtime.enqueue_agent_job("course-1", "rebalance_daily_plan", {})
    generation = agent_runtime.enqueue_agent_job("course-1", "approve_strategy_documents", {"repairOnly": True})

    claimed = agent_runtime._claim_job()

    assert claimed is not None
    assert claimed["id"] == generation
    assert claimed["jobType"] == "approve_strategy_documents"
    assert claimed["id"] != maintenance


def test_cancelled_job_stays_cancelled_after_worker_returns(monkeypatch, tmp_path):
    _use_temp_database(monkeypatch, tmp_path)
    job_id = agent_runtime.enqueue_agent_job("course-1", "approve_strategy_documents", {})
    claimed = agent_runtime._claim_job()
    assert claimed and claimed["id"] == job_id

    cancelled = agent_runtime.cancel_agent_job(job_id)
    assert cancelled["status"] == "cancelled"
    agent_runtime._complete_job(job_id, {"shouldNotPersist": True})
    assert agent_runtime.get_agent_job(job_id)["status"] == "cancelled"


def test_renew_job_lease_extends_running_job(monkeypatch, tmp_path):
    database = _use_temp_database(monkeypatch, tmp_path)
    job_id = agent_runtime.enqueue_agent_job("course-1", "approve_strategy_documents", {})
    claimed = agent_runtime._claim_job()
    assert claimed and claimed["id"] == job_id

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE agent_jobs SET lease_until = '2000-01-01T00:00:00' WHERE id = ?", (job_id,))
        connection.commit()
    agent_runtime._renew_job_lease(job_id)
    with sqlite3.connect(database) as connection:
        lease_until = connection.execute("SELECT lease_until FROM agent_jobs WHERE id = ?", (job_id,)).fetchone()[0]

    assert lease_until > "2000-01-01T00:00:00"
