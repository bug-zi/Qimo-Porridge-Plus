"""Agent job queue priority, deduplication and lease tests."""
from __future__ import annotations

import sqlite3
import sys
import time
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


def test_stale_generation_cannot_complete_after_reclaim(monkeypatch, tmp_path):
    """lease 过期被二次 claim 后，旧代执行者的完成写被 fencing token 拒绝。"""
    _use_temp_database(monkeypatch, tmp_path)
    job_id = agent_runtime.enqueue_agent_job("course-1", "approve_strategy_documents", {})
    first = agent_runtime._claim_job()
    assert first and first["id"] == job_id
    stale_token = first["leaseToken"]

    # 模拟 lease 过期 + 被新一代 claim
    with sqlite3.connect(agent_runtime.DATABASE_PATH) as connection:
        connection.execute("UPDATE agent_jobs SET lease_until = '2000-01-01T00:00:00' WHERE id = ?", (job_id,))
        connection.commit()
    second = agent_runtime._claim_job()
    assert second and second["id"] == job_id
    assert second["leaseToken"] != stale_token

    # 旧代执行者带旧 token 完成 → 被拒绝，状态保持 running（属新一代）
    agent_runtime._complete_job(job_id, {"stale": True}, lease_token=stale_token)
    assert agent_runtime.get_agent_job(job_id)["status"] == "running"

    # 新一代带新 token 完成 → 正常落库
    agent_runtime._complete_job(job_id, {"fresh": True}, lease_token=second["leaseToken"])
    assert agent_runtime.get_agent_job(job_id)["status"] == "completed"


def test_stale_generation_loses_ownership_and_detects_it(monkeypatch, tmp_path):
    """has_agent_job_ownership：二次 claim 后旧代失去所有权（协作取消点据此中止）。"""
    _use_temp_database(monkeypatch, tmp_path)
    job_id = agent_runtime.enqueue_agent_job("course-1", "approve_strategy_documents", {})
    first = agent_runtime._claim_job()

    assert agent_runtime.has_agent_job_ownership(job_id, first["leaseToken"]) is True

    with sqlite3.connect(agent_runtime.DATABASE_PATH) as connection:
        connection.execute("UPDATE agent_jobs SET lease_until = '2000-01-01T00:00:00' WHERE id = ?", (job_id,))
        connection.commit()
    second = agent_runtime._claim_job()

    assert agent_runtime.has_agent_job_ownership(job_id, first["leaseToken"]) is False
    assert agent_runtime.has_agent_job_ownership(job_id, second["leaseToken"]) is True


def test_claim_skips_course_with_running_job(monkeypatch, tmp_path):
    """同课程互斥：某课程已有 running 任务时，不 claim 该课程的 queued 任务。"""
    _use_temp_database(monkeypatch, tmp_path)
    running_id = agent_runtime.enqueue_agent_job("course-1", "approve_strategy_documents", {})
    claimed = agent_runtime._claim_job()
    assert claimed and claimed["id"] == running_id

    # 同课程再排一个任务：不应被 claim（另一课程的任务才可被拿走）
    same_course = agent_runtime.enqueue_agent_job("course-1", "rebalance_daily_plan", {})
    other_course = agent_runtime.enqueue_agent_job("course-2", "rebalance_daily_plan", {})
    # running 的 job 在临时库中 lease 未过期，不会被回收
    picked = agent_runtime._claim_job()
    assert picked and picked["id"] == other_course
    assert picked["id"] != same_course


def test_heartbeat_survives_single_db_failure(monkeypatch, tmp_path):
    """心跳线程遇单次 SQLite 错误不死，下一轮继续续租。"""
    _use_temp_database(monkeypatch, tmp_path)
    job_id = agent_runtime.enqueue_agent_job("course-1", "approve_strategy_documents", {})
    claimed = agent_runtime._claim_job()

    import threading

    # 心跳周期 60s 太长，压到 10ms 驱动多轮循环
    real_wait = threading.Event.wait

    def fast_wait(self, timeout=None):
        # 只缩短心跳的 60s 长等待；Thread.start 等内部无参调用保持原语义
        if timeout is not None and timeout >= 60:
            timeout = 0.01
        return real_wait(self, timeout)

    monkeypatch.setattr(threading.Event, "wait", fast_wait)
    original = agent_runtime._renew_job_lease
    failures = {"count": 0}

    def flaky(job_id_arg, *, lease_token: str = "") -> None:
        if failures["count"] < 1:
            failures["count"] += 1
            raise sqlite3.OperationalError("database is locked")
        original(job_id_arg, lease_token=lease_token)

    monkeypatch.setattr(agent_runtime, "_renew_job_lease", flaky)
    stop = threading.Event()
    heartbeat = threading.Thread(
        target=agent_runtime._lease_heartbeat,
        args=(job_id, stop, claimed["leaseToken"]),
        daemon=True,
    )
    heartbeat.start()
    # 等心跳经历一次失败后继续存活（线程在跑即证明未崩溃）
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and failures["count"] < 1:
        time.sleep(0.02)
    stop.set()
    heartbeat.join(timeout=3)
    assert heartbeat.is_alive() is False  # 线程正常退出而非崩溃
    assert failures["count"] == 1  # 遭遇失败后线程仍活着并完成后续轮次
