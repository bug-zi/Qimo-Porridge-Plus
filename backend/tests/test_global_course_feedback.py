from __future__ import annotations

from copy import deepcopy

import app.course_feedback_service as service


def _workspace() -> dict:
    guide = {
        "objectives": ["掌握原理"], "sourceHighlights": [],
        "examPoints": [{"id": "point-1", "title": "考点", "explanation": "原讲解"}],
        "concepts": [{"title": "概念", "body": "原讲解", "formula": ""}],
        "workedExamples": [{"id": "ex-1", "problem": "原题", "steps": ["原步骤"], "answer": "原答案"}],
        "checklist": ["原检查项"], "selfTestQuestionIds": [],
    }
    from app.study_service import _build_study_guide_sections
    guide["sections"] = _build_study_guide_sections(guide)
    return {"tasks": [{"id": "task-1", "title": "测试课程", "studyGuide": guide}]}


def _stores(monkeypatch, workspace: dict):
    entries: list[dict] = []; rules = {"version": 1, "rules": [], "summaryPrompt": "", "updatedAt": ""}
    monkeypatch.setattr("app.study_service.load_workspace", lambda *_args, **_kwargs: deepcopy(workspace))
    monkeypatch.setattr(service, "_read_feedback_entries", lambda _course_id: deepcopy(entries))
    monkeypatch.setattr(service, "_write_feedback_entries", lambda _course_id, value: entries.__setitem__(slice(None), deepcopy(value)))
    monkeypatch.setattr(service, "_read_rules_store", lambda _course_id: deepcopy(rules))
    monkeypatch.setattr(service, "_write_rules_store", lambda _course_id, value: rules.update(deepcopy(value)))
    return entries, rules


def _model(workspace: dict):
    def model_json(_task_prompt: str, _payload: str, _system: str) -> dict:
        revised = deepcopy(workspace["tasks"][0]["studyGuide"]["sections"][1])
        revised["concepts"].append({"title": "小节总结", "body": "新增总结", "formula": ""})
        analysis = {"problemTypes": ["other"], "diagnosis": "需要调整小节", "suggestedRewrite": "", "ruleCandidate": {"type": "teaching_style", "title": "小节增加总结", "preferredPattern": "在小节末尾增加总结"}}
        return {"revisedSection": revised, "changeSummary": "讲解小节增加总结", "rationale": "便于复习", "analysis": analysis}
    return model_json


def test_submit_feedback_targets_only_current_subsection(monkeypatch) -> None:
    workspace = _workspace(); entries, rules = _stores(monkeypatch, workspace)
    model = _model(workspace); calls = 0
    def counted_model(*args):
        nonlocal calls
        calls += 1
        return model(*args)
    result = service.submit_global_course_feedback("course-1", task_id="task-1", section_id="method", section_index=1, user_comment="在本小节末尾加总结", model_json=counted_model)
    assert calls == 1
    assert result["proposal"]["sectionId"] == "method"
    assert result["proposal"]["revisedSection"]["concepts"][-1]["title"] == "小节总结"
    assert "revisedStudyGuide" not in result["proposal"]
    assert entries[0]["context"]["feedbackScope"] == "section"
    assert entries[0]["context"]["sectionIndex"] == 1
    assert rules["rules"][0]["sourceFeedbackIds"] == [result["feedbackId"]]


def test_apply_subsection_preserves_other_three_sections(monkeypatch) -> None:
    workspace = _workspace(); original = deepcopy(workspace["tasks"][0]["studyGuide"]); revised = deepcopy(original["sections"][1]); revised["concepts"].append({"title": "新增", "body": "总结"})
    proposal = {"taskId": "task-1", "sectionId": "method", "sectionIndex": 1, "baseRevision": service._guide_revision_token(original), "revisedSection": revised, "changeSummary": "追加总结"}
    entries = [{"id": "feedback-1", "rewriteSession": {"latestProposal": proposal, "attempts": [{"accepted": False}]}}]; saved = {}
    monkeypatch.setattr(service, "_read_feedback_entries", lambda _id: entries); monkeypatch.setattr(service, "_write_feedback_entries", lambda *_args: None)
    monkeypatch.setattr("app.study_service.load_workspace", lambda *_args, **_kwargs: deepcopy(workspace)); monkeypatch.setattr("app.study_service.save_workspace", lambda value, _id: saved.update(deepcopy(value)))
    service.apply_global_course_feedback("course-1", "feedback-1")
    guide = saved["tasks"][0]["studyGuide"]
    assert guide["sections"][0] == original["sections"][0]
    assert guide["sections"][2] == original["sections"][2]
    assert guide["sections"][3] == original["sections"][3]
    assert guide["concepts"][-1]["title"] == "新增"
    assert entries[0]["rewriteSession"]["acceptedGlobalRewrite"]["sectionId"] == "method"


def test_apply_subsection_rejects_stale_course(monkeypatch) -> None:
    workspace = _workspace(); proposal = {"taskId": "task-1", "sectionId": "method", "sectionIndex": 1, "baseRevision": "stale", "revisedSection": {"id": "method"}}
    monkeypatch.setattr(service, "_read_feedback_entries", lambda _id: [{"id": "f", "rewriteSession": {"latestProposal": proposal}}]); monkeypatch.setattr("app.study_service.load_workspace", lambda *_args, **_kwargs: deepcopy(workspace))
    try: service.apply_global_course_feedback("c", "f")
    except ValueError as error: assert "已发生变化" in str(error)
    else: raise AssertionError("stale proposal should fail")
