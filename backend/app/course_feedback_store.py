from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any, Callable, TypeVar

from .study_service import _atomic_write_text, _course_data_directory

T = TypeVar("T")
FEEDBACK_VERSION = 1
MAX_STRONG_DIRECTIVES = 40
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def course_feedback_lock(course_id: str) -> threading.RLock:
    """Return the process-local re-entrant lock for one course feedback store."""
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(course_id, threading.RLock())


def _feedback_directory(course_id: str) -> Path:
    return _course_data_directory(course_id) / "feedback"


def _feedback_log_path(course_id: str) -> Path:
    return _feedback_directory(course_id) / "feedback.jsonl"


def _rules_path(course_id: str) -> Path:
    return _feedback_directory(course_id) / "optimization_rules.json"


def _read_feedback_entries_unlocked(course_id: str) -> list[dict[str, Any]]:
    path = _feedback_log_path(course_id)
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            entries.append(item)
    return entries


def _write_feedback_entries_unlocked(course_id: str, entries: list[dict[str, Any]]) -> None:
    content = "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in entries)
    _atomic_write_text(_feedback_log_path(course_id), content + ("\n" if content else ""))


def read_feedback_entries(course_id: str) -> list[dict[str, Any]]:
    with course_feedback_lock(course_id):
        return copy.deepcopy(_read_feedback_entries_unlocked(course_id))


def write_feedback_entries(course_id: str, entries: list[dict[str, Any]]) -> None:
    with course_feedback_lock(course_id):
        _write_feedback_entries_unlocked(course_id, copy.deepcopy(entries))


def mutate_feedback_entries(course_id: str, mutation: Callable[[list[dict[str, Any]]], T]) -> T:
    """Run a feedback read-modify-write atomically under the course lock."""
    with course_feedback_lock(course_id):
        entries = _read_feedback_entries_unlocked(course_id)
        result = mutation(entries)
        _write_feedback_entries_unlocked(course_id, entries)
        return result


def _empty_rules_store() -> dict[str, Any]:
    return {"version": FEEDBACK_VERSION, "rules": [], "strongDirectives": [], "summaryPrompt": "", "updatedAt": ""}


def _read_rules_store_unlocked(course_id: str) -> dict[str, Any]:
    path = _rules_path(course_id)
    if not path.exists():
        return _empty_rules_store()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_rules_store()
    if not isinstance(payload, dict):
        return _empty_rules_store()
    rules = payload.get("rules") if isinstance(payload.get("rules"), list) else []
    directives = payload.get("strongDirectives") if isinstance(payload.get("strongDirectives"), list) else []
    return {
        "version": int(payload.get("version") or FEEDBACK_VERSION),
        "rules": [item for item in rules if isinstance(item, dict)],
        "strongDirectives": [item for item in directives if isinstance(item, dict)][:MAX_STRONG_DIRECTIVES],
        "summaryPrompt": str(payload.get("summaryPrompt") or ""),
        "updatedAt": str(payload.get("updatedAt") or ""),
    }


def _write_rules_store_unlocked(course_id: str, store: dict[str, Any]) -> None:
    _atomic_write_text(_rules_path(course_id), json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def read_rules_store(course_id: str) -> dict[str, Any]:
    with course_feedback_lock(course_id):
        return copy.deepcopy(_read_rules_store_unlocked(course_id))


def write_rules_store(course_id: str, store: dict[str, Any]) -> None:
    with course_feedback_lock(course_id):
        _write_rules_store_unlocked(course_id, copy.deepcopy(store))


def mutate_rules_store(course_id: str, mutation: Callable[[dict[str, Any]], T]) -> T:
    """Run a rules read-modify-write atomically under the same course lock."""
    with course_feedback_lock(course_id):
        store = _read_rules_store_unlocked(course_id)
        result = mutation(store)
        _write_rules_store_unlocked(course_id, store)
        return result
