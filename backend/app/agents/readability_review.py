from __future__ import annotations

from datetime import datetime
import re
from typing import Any

READABILITY_REVIEW_VERSION = 1

def _text(value: object) -> str:
    return str(value or "").strip()


def _issue(code: str, message: str, field: str, *, severity: str = "warning", penalty: int = 6) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, "field": field, "penalty": penalty}


def _visible_paragraphs(value: object) -> list[str]:
    text = _text(value)
    return [part.strip() for part in re.split(r"\n\s*\n|(?<=[。！？!?])\s*\n", text) if part.strip()]


def _review_long_text(value: object, field: str, label: str, issues: list[dict[str, Any]], *, limit: int = 260) -> None:
    text = _text(value)
    if not text:
        return
    paragraphs = _visible_paragraphs(text)
    longest = max((len(item) for item in paragraphs), default=0)
    sentence_count = len([item for item in re.split(r"[。！？!?]+", text) if item.strip()])
    if longest > limit:
        issues.append(_issue("dense-paragraph", f"{label}存在超过 {limit} 字的连续段落，建议按观点或推理步骤分段。", field, penalty=8))
    if len(text) > 180 and sentence_count <= 2:
        issues.append(_issue("long-sentence", f"{label}句子过长，建议拆成结论、解释与边界。", field, penalty=6))


def _review_list(value: object, field: str, label: str, issues: list[dict[str, Any]]) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        issues.append(_issue("invalid-list", f"{label}没有使用可扫描的列表结构。", field, severity="error", penalty=10))
        return
    values = [_text(item) for item in value if _text(item)]
    if len(values) != len(value):
        issues.append(_issue("empty-list-item", f"{label}包含空项目。", field, penalty=3))
    if len(values) != len(set(values)):
        issues.append(_issue("duplicate-list-item", f"{label}包含完全重复的项目。", field, penalty=4))
    if any(len(item) > 180 for item in values):
        issues.append(_issue("dense-list-item", f"{label}中有过长项目，建议拆成多个步骤。", field, penalty=5))


def review_study_guide(task: dict[str, Any], content_style: str = "standard") -> dict[str, Any]:
    task_id = _text(task.get("id"))
    guide = task.get("studyGuide")
    if not isinstance(guide, dict):
        return {
            "version": READABILITY_REVIEW_VERSION,
            "status": "unavailable",
            "issues": [_issue("missing-guide", "课程正文尚未生成，暂时无法审核排版。", "studyGuide", severity="info", penalty=0)],
            "summary": "正文尚未生成",
        }

    issues: list[dict[str, Any]] = []
    title = _text(task.get("title"))
    if not title:
        issues.append(_issue("missing-title", "课程缺少可识别的标题。", "task.title", severity="error", penalty=12))
    elif len(title) > 36:
        issues.append(_issue("long-title", "课程标题偏长，目录中不易快速扫描。", "task.title", penalty=4))

    points = guide.get("examPoints")
    if not isinstance(points, list) or not points:
        issues.append(_issue("missing-exam-points", "正文缺少分层考点，阅读路径不清晰。", "studyGuide.examPoints", severity="error", penalty=12))
        points = []
    point_titles: list[str] = []
    for index, point in enumerate(points):
        if not isinstance(point, dict):
            continue
        field = f"studyGuide.examPoints[{index}]"
        point_title = _text(point.get("title"))
        if point_title:
            point_titles.append(point_title)
        _review_long_text(point.get("explanation"), f"{field}.explanation", f"考点“{point_title or index + 1}”的讲解", issues)
        _review_list(point.get("procedure"), f"{field}.procedure", "解题步骤", issues)
        _review_list(point.get("pitfalls"), f"{field}.pitfalls", "易错点", issues)
        formulas = point.get("formulas", [])
        if isinstance(formulas, list):
            for formula_index, formula in enumerate(formulas):
                if not isinstance(formula, dict):
                    continue
                formula_field = f"{field}.formulas[{formula_index}]"
                if not _text(formula.get("meaning")) or not _text(formula.get("conditions")):
                    issues.append(_issue("formula-context", "公式缺少含义或适用条件，阅读时容易误用。", formula_field, severity="error", penalty=9))
    if len(point_titles) != len(set(point_titles)):
        issues.append(_issue("duplicate-heading", "多个考点使用了完全相同的标题，层级不易区分。", "studyGuide.examPoints", penalty=7))

    examples = guide.get("workedExamples", [])
    if isinstance(examples, list):
        example_titles: list[str] = []
        for index, example in enumerate(examples):
            if not isinstance(example, dict):
                continue
            field = f"studyGuide.workedExamples[{index}]"
            example_title = _text(example.get("title"))
            if example_title:
                example_titles.append(example_title)
            for key, label, limit in (("problem", "例题题干", 320), ("analysis", "题型分析", 240), ("answer", "例题答案", 220)):
                _review_long_text(example.get(key), f"{field}.{key}", label, issues, limit=limit)
            _review_list(example.get("steps"), f"{field}.steps", "例题步骤", issues)
        if len(example_titles) != len(set(example_titles)):
            issues.append(_issue("duplicate-example-heading", "多道例题标题完全相同，不利于回看定位。", "studyGuide.workedExamples", penalty=5))

    sections = guide.get("sections", [])
    if isinstance(sections, list):
        section_titles: list[str] = []
        for index, section in enumerate(sections):
            if not isinstance(section, dict):
                continue
            field = f"studyGuide.sections[{index}]"
            section_title = _text(section.get("title"))
            if section_title:
                section_titles.append(section_title)
            _review_long_text(section.get("narrative"), f"{field}.narrative", f"“{section_title or index + 1}”正文", issues, limit=240)
            beats = section.get("explanationBeats", [])
            if isinstance(beats, list):
                beat_titles: list[str] = []
                for beat_index, beat in enumerate(beats):
                    if not isinstance(beat, dict):
                        continue
                    heading = _text(beat.get("heading"))
                    if heading:
                        beat_titles.append(heading)
                    _review_long_text(beat.get("body"), f"{field}.explanationBeats[{beat_index}].body", f"讲解“{heading or beat_index + 1}”", issues, limit=240)
                if len(beat_titles) != len(set(beat_titles)):
                    issues.append(_issue("duplicate-subheading", "讲解中存在重复小标题。", f"{field}.explanationBeats", penalty=6))
        if len(section_titles) != len(set(section_titles)):
            issues.append(_issue("duplicate-section-heading", "课程分页标题重复，不利于建立阅读位置感。", "studyGuide.sections", penalty=6))

    if content_style == "story":
        expected = ["preparation", "explanation", "examples", "self-check"]
        actual = [_text(item.get("kind")) for item in sections if isinstance(item, dict)] if isinstance(sections, list) else []
        if actual != expected:
            issues.append(_issue("story-page-flow", "故事版没有按课前准备、讲解、例题、自测形成四段阅读流程。", "studyGuide.sections", severity="error", penalty=12))
        story = guide.get("storyContext")
        if isinstance(story, dict) and (not _text(story.get("incomingQuestion")) or not _text(story.get("outgoingQuestion"))):
            issues.append(_issue("story-transition", "故事主线缺少承上启下的问题。", "studyGuide.storyContext", penalty=7))

    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in issues:
        key = (str(item["code"]), str(item["field"]))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    public_issues = [{key: value for key, value in item.items() if key != "penalty"} for item in unique]
    status = "passed" if not any(item["severity"] == "error" for item in public_issues) else "attention"
    return {
        "version": READABILITY_REVIEW_VERSION,
        "status": status,
        "issues": public_issues,
        "summary": "排版清晰，可直接阅读" if status == "passed" else f"发现 {len(public_issues)} 项可读性建议",
        "taskId": task_id,
    }


def attach_readability_review(task: dict[str, Any], content_style: str = "standard") -> dict[str, Any]:
    report = review_study_guide(task, content_style)
    guide = task.get("studyGuide")
    if isinstance(guide, dict):
        guide["readabilityReview"] = report
    return report


def build_course_readability_review(tasks: list[dict[str, Any]], content_style: str = "standard", *, reviewed_at: str | None = None) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    pending = 0
    for task in tasks:
        if not isinstance(task, dict) or _text(task.get("kind")) == "orientation":
            continue
        if not isinstance(task.get("studyGuide"), dict):
            pending += 1
            continue
        reports.append(attach_readability_review(task, content_style))
    attention = sum(report["status"] == "attention" for report in reports)
    passed = sum(report["status"] == "passed" for report in reports)
    return {
        "version": READABILITY_REVIEW_VERSION,
        "status": "pending" if not reports else ("passed" if attention == 0 and pending == 0 else "attention"),
        "reviewedAt": reviewed_at or datetime.now().isoformat(timespec="seconds"),
        "reviewedLessonCount": len(reports),
        "passedLessonCount": passed,
        "attentionLessonCount": attention,
        "pendingLessonCount": pending,
        "summary": "尚无可审核课程" if not reports else ("全部课程排版清晰" if attention == 0 and pending == 0 else f"{attention} 课需要关注，{pending} 课待生成"),
        "lessons": [{"taskId": report.get("taskId", ""), "status": report["status"], "issueCount": len(report["issues"])} for report in reports],
    }
