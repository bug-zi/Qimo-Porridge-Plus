from __future__ import annotations

import threading
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Iterator

_LOCK = threading.Lock()
_CONTEXT: ContextVar[dict[str, str]] = ContextVar("model_usage_context", default={})
_SCOPES: dict[str, dict[str, Any]] = {}
_RECENT_LIMIT = 50


def _empty_scope(job_id: str = "", run_id: str = "") -> dict[str, Any]:
    return {
        "jobId": job_id,
        "runId": run_id,
        "promptTokens": 0,
        "completionTokens": 0,
        "totalTokens": 0,
        "calls": 0,
        "failures": 0,
        "startedAt": "",
        "updatedAt": "",
        "currentCall": {"model": "", "startedAt": "", "stage": "", "taskId": "", "attempt": 0},
        "stages": {},
        "recent": deque(maxlen=_RECENT_LIMIT),
    }


def _scope_key(context: dict[str, str]) -> str:
    return context.get("jobId") or context.get("runId") or ""


@contextmanager
def model_call_scope(*, job_id: str = "", run_id: str = "", stage: str = "", task_id: str = "") -> Iterator[None]:
    token = _CONTEXT.set({"jobId": job_id, "runId": run_id, "stage": stage, "taskId": task_id})
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def record_call_start(model_name: str) -> None:
    context = _CONTEXT.get()
    key = _scope_key(context)
    if not key:
        return
    now = datetime.now().isoformat(timespec="seconds")
    with _LOCK:
        scope = _SCOPES.setdefault(key, _empty_scope(context.get("jobId", ""), context.get("runId", "")))
        stage_name = context.get("stage") or "unknown"
        stage = scope["stages"].setdefault(stage_name, {"calls": 0, "failures": 0, "promptTokens": 0, "completionTokens": 0, "totalTokens": 0})
        attempt = int(stage.get("calls", 0)) + int(stage.get("failures", 0)) + 1
        if not scope["startedAt"]:
            scope["startedAt"] = now
        scope["currentCall"] = {
            "model": model_name,
            "startedAt": now,
            "stage": stage_name,
            "taskId": context.get("taskId", ""),
            "attempt": attempt,
        }


def record_call_result(data: dict[str, Any], model_name: str, *, failed: bool = False) -> None:
    context = _CONTEXT.get()
    key = _scope_key(context)
    if not key:
        return
    now = datetime.now().isoformat(timespec="seconds")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = prompt_tokens + completion_tokens
    stage_name = context.get("stage") or "unknown"
    with _LOCK:
        scope = _SCOPES.setdefault(key, _empty_scope(context.get("jobId", ""), context.get("runId", "")))
        stage = scope["stages"].setdefault(stage_name, {"calls": 0, "failures": 0, "promptTokens": 0, "completionTokens": 0, "totalTokens": 0})
        if failed:
            scope["failures"] += 1
            stage["failures"] += 1
        else:
            scope["calls"] += 1
            scope["promptTokens"] += prompt_tokens
            scope["completionTokens"] += completion_tokens
            scope["totalTokens"] += total_tokens
            stage["calls"] += 1
            stage["promptTokens"] += prompt_tokens
            stage["completionTokens"] += completion_tokens
            stage["totalTokens"] += total_tokens
        scope["updatedAt"] = now
        current = dict(scope["currentCall"])
        scope["currentCall"] = {"model": "", "startedAt": "", "stage": "", "taskId": "", "attempt": 0}
        scope["recent"].append({
            "at": now,
            "model": model_name,
            "stage": stage_name,
            "taskId": context.get("taskId", ""),
            "attempt": current.get("attempt", 0),
            "failed": failed,
            "promptTokens": prompt_tokens,
            "completionTokens": completion_tokens,
            "totalTokens": total_tokens,
        })


def get_scoped_model_usage(scope_id: str) -> dict[str, Any] | None:
    if not scope_id:
        return None
    with _LOCK:
        scope = _SCOPES.get(scope_id)
        if scope is None:
            return None
        return {**scope, "stages": {name: dict(value) for name, value in scope["stages"].items()}, "recent": list(scope["recent"])}
