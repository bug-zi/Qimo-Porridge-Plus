from __future__ import annotations

import app.course_feedback_service as service
import app.course_feedback_store as store


def _isolate(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(store, "_course_data_directory", lambda course_id: tmp_path / course_id)


def _analysis() -> dict:
    return {
        "problemTypes": ["other"],
        "diagnosis": "多余",
        "suggestedRewrite": "",
        "ruleCandidate": {"type": "teaching_style", "title": "避免多余题", "preferredPattern": "只保留必要问题"},
    }


def test_store_mutation_is_atomic_per_course(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    store.mutate_feedback_entries("course-1", lambda entries: entries.append({"id": "one"}))
    store.mutate_feedback_entries("course-1", lambda entries: entries.append({"id": "two"}))
    assert [item["id"] for item in store.read_feedback_entries("course-1")] == ["one", "two"]


def test_delete_intent_including_shanqu_never_calls_rewriter(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    calls = 0

    def model(_prompt: str, _payload: str, _system: str) -> dict:
        nonlocal calls
        calls += 1
        return _analysis()

    result = service.submit_course_feedback_with_rewrite(
        "course-1", selected_text="多余问题", user_comment="请你删去", context={"taskId": "task-1"}, model_json=model,
    )
    assert calls == 1
    assert result["status"] == "awaiting_confirmation"
    assert result["rewriteProposal"]["rewrittenText"] == ""
    entry = store.read_feedback_entries("course-1")[0]
    assert entry["rewriteSession"]["status"] == "open"
    assert store.read_rules_store("course-1")["rules"][0]["status"] == "proposed"


def test_rewrite_error_is_persisted_and_retryable(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    calls = 0

    def model(_prompt: str, _payload: str, _system: str) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _analysis()
        raise ValueError("rewriter unavailable")

    result = service.submit_course_feedback_with_rewrite(
        "course-1", selected_text="原文", user_comment="改短一点", context={}, model_json=model,
    )
    assert result["feedbackSaved"] is True
    assert result["proposalStatus"] == "failed"
    assert result["canRetryProposal"] is True
    assert "rewriter unavailable" in result["rewriteError"]
    assert store.read_feedback_entries("course-1")[0]["rewriteError"] == "rewriter unavailable"


def test_abandon_compacts_open_session_and_hides_it(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    store.write_feedback_entries("course-1", [{
        "id": "feedback-1", "status": "awaiting_confirmation", "userComment": "改掉",
        "rewriteSession": {"status": "open", "latestProposal": {"rewrittenText": "large"}, "attempts": [{"version": 1, "inputComment": "a", "rewrittenText": "large", "createdAt": "now"}]},
    }])
    service.abandon_course_feedback("course-1", "feedback-1")
    entry = store.read_feedback_entries("course-1")[0]
    assert entry["status"] == "abandoned"
    assert "latestProposal" not in entry["rewriteSession"]
    assert "rewrittenText" not in entry["rewriteSession"]["attempts"][0]
    assert service.get_open_course_feedback("course-1")["items"] == []


def test_unaccepted_legacy_feedback_does_not_become_must(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    store.write_feedback_entries("course-1", [{"id": "legacy", "userComment": "不要题目", "context": {"feedbackScope": "section"}}])
    assert service.get_course_strong_directives("course-1") == []

def test_rule_maintenance_rebuilds_active_prompt(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    store.write_rules_store("course-1", {"version": 1, "rules": [{"id": "rule-1", "status": "proposed", "title": "少出题", "preferredPattern": "只保留必要题", "sourceFeedbackIds": ["f-1"]}], "strongDirectives": [], "summaryPrompt": "", "updatedAt": ""})
    activated = service.update_course_feedback_rule("course-1", "rule-1", status="active")
    assert activated["rule"]["status"] == "active"
    assert "只保留必要题" in service.get_course_feedback_rules_prompt("course-1")
    service.delete_course_feedback_rule("course-1", "rule-1")
    assert service.get_course_feedback_rules_prompt("course-1") == ""


def test_submit_transactions_share_one_course_rlock(monkeypatch) -> None:
    import threading
    import time

    entries: list[dict] = []
    active = 0
    peak = 0
    gate = threading.Lock()
    monkeypatch.setattr(service, "_read_feedback_entries", lambda _course_id: list(entries))
    monkeypatch.setattr(service, "_write_feedback_entries", lambda _course_id, value: entries.__setitem__(slice(None), value))
    monkeypatch.setattr(service, "_read_rules_store", lambda _course_id: {"version": 1, "rules": [], "strongDirectives": [], "summaryPrompt": "", "updatedAt": ""})
    monkeypatch.setattr(service, "_write_rules_store", lambda *_args: None)

    def model(*_args) -> dict:
        nonlocal active, peak
        with gate:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with gate:
            active -= 1
        return _analysis()

    threads = [threading.Thread(target=service.submit_course_feedback, args=("course-1",), kwargs={"selected_text": str(index), "user_comment": "删去", "context": {}, "model_json": model}) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert peak == 1
    assert len(entries) == 2


def test_merge_feedback_rules_combines_sources_and_rebuilds_prompt(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    store.write_rules_store("course-1", {
        "version": 1,
        "rules": [
            {"id": "target", "status": "proposed", "title": "具体场景", "preferredPattern": "先给场景", "sourceFeedbackIds": ["f1"], "weight": 1.0},
            {"id": "source", "status": "active", "title": "减少模板话", "preferredPattern": "减少模板话", "sourceFeedbackIds": ["f2"], "proposedSourceFeedbackIds": ["f3"], "weight": 1.25},
        ],
        "strongDirectives": [],
        "summaryPrompt": "",
        "updatedAt": "",
    })

    result = service.merge_course_feedback_rules("course-1", "target", ["source"])

    assert result["mergedRuleIds"] == ["source"]
    assert result["rule"]["status"] == "active"
    assert result["rule"]["sourceFeedbackIds"] == ["f1", "f2"]
    assert result["rule"]["proposedSourceFeedbackIds"] == ["f3"]
    assert result["rule"]["weight"] == 2.25
    assert [rule["id"] for rule in result["rules"]["rules"]] == ["target"]
    assert "具体场景" in result["rules"]["summaryPrompt"]
