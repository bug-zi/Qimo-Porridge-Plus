from __future__ import annotations

import app.course_feedback_service as feedback
from app.agents.workflow import _strong_feedback_issues


def test_rules_prompt_recovers_accepted_legacy_section_feedback_as_must(monkeypatch) -> None:
    monkeypatch.setattr(feedback, "_read_rules_store", lambda _course_id: {"rules": [], "strongDirectives": [], "summaryPrompt": ""})
    monkeypatch.setattr(feedback, "_read_feedback_entries", lambda _course_id: [{
        "id": "old-feedback", "createdAt": "2026-01-01T00:00:00", "status": "accepted",
        "userComment": "只需要有背景引导+本节课关键词的解释+01结尾与02-讲解开头衔接",
        "context": {"feedbackScope": "section", "sectionId": "preparation", "sectionLabel": "课前准备"},
    }])
    prompt = feedback.get_course_feedback_rules_prompt("course-1")
    assert "最高优先级生成合同" in prompt
    assert "MUST-1 [课前准备]" in prompt
    assert "只需要有背景引导" in prompt


def test_preparation_old_template_fails_strong_feedback_review() -> None:
    guide = {"sections": [
        {"kind": "preparation", "title": "准备", "narrative": "背景", "questions": ["问题1", "问题2", "问题3"], "terms": [{"term": "进程", "meaning": "运行中的程序"}]},
        {"kind": "explanation", "title": "讲解", "narrative": "现在开始讲解。"},
    ]}
    issues = _strong_feedback_issues(guide, ["MUST-1 [课前准备] 只需要背景引导、关键词解释、01与02衔接"])
    assert any("3至5题旧模板" in issue for issue in issues)


def test_compliant_preparation_passes_strong_feedback_review() -> None:
    guide = {"sections": [
        {"kind": "preparation", "title": "准备", "narrative": "一个进程正在等待事件。接下来从状态变化解释它为什么等待。", "questions": ["状态为什么会变化？"], "terms": [{"term": "进程状态", "meaning": "进程当前所处的运行阶段"}]},
        {"kind": "explanation", "title": "讲解", "narrative": "先从刚才的等待状态开始分析。"},
    ]}
    assert _strong_feedback_issues(guide, ["MUST-1 [课前准备] 只需要背景引导、关键词解释、01与02衔接"]) == []
