"""工作空间域（阶段2-4 从 study_service.py 抽取）。

职责：workspace.json 的加载/保存/并发锁、课程目录路径解析、
工作区内容质量迁移（WORKSPACE_CONTENT_VERSION 升级路径）、
空工作区初始化、mind_map 读写。

依赖方向：workspace → paths / study_scheduler / agents.question_generation，
禁止模块级 import study_service（成环）。load_workspace / save_workspace /
scan_course_materials / _mark_material_memory / _workspace_needs_material_refresh
属于跨域缝合点——测试惯用 monkeypatch.setattr(study_service, ...) 打桩，
故本模块在函数体内延迟 import study_service，调用时读取其（可能已被
patch 的）命名空间，打桩面与拆分前完全一致（materials.py 既有惯例）。
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import paths, study_scheduler
from .agents.question_generation import _shuffle_single_choice_options

WORKSPACE_CONTENT_VERSION = 4

_WORKSPACE_LOCKS: dict[str, threading.RLock] = {}
_WORKSPACE_LOCKS_GUARD = threading.Lock()
_CONTENT_GENERATION_LOCKS: dict[str, threading.Lock] = {}
_CONTENT_GENERATION_LOCKS_GUARD = threading.Lock()


def _validate_course_id(course_id: str) -> str:
    normalized = course_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}", normalized):
        raise ValueError("课程 ID 无效")
    return normalized


def _course_data_directory(course_id: str) -> Path:
    return paths.COURSES_DATA_DIRECTORY / _validate_course_id(course_id)


def _workspace_path(course_id: str) -> Path:
    return _course_data_directory(course_id) / "workspace.json"


def _mind_map_path(course_id: str) -> Path:
    return _course_data_directory(course_id) / "mind_map.json"


def _course_material_directory(course_id: str) -> Path:
    return _course_data_directory(course_id) / "materials"


def _course_overview_path(course_id: str) -> Path:
    return _course_material_directory(course_id) / "课程复习总览.md"


def _strategy_directory(course_id: str) -> Path:
    return _course_data_directory(course_id) / "strategy"


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary_path.write_text(content, encoding="utf-8")
    os.replace(temporary_path, path)


def _review_days_from_exam_date(exam_date: Any, *, today: date | None = None) -> int | None:
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(exam_date or "").strip())
    if not match:
        return None
    try:
        exam_day = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    current_day = today or datetime.now().date()
    return min(30, max(1, (exam_day - current_day).days))


def _complete_study_guide(guide: Any) -> bool:
    if not isinstance(guide, dict):
        return False
    exam_points = guide.get("examPoints")
    if isinstance(exam_points, list) and exam_points:
        return all(
            isinstance(point, dict)
            and str(point.get("id", "")).strip()
            and str(point.get("title", "")).strip()
            and str(point.get("explanation", "")).strip()
            for point in exam_points
        )
    return any(
        isinstance(guide.get(key), list) and any(str(item).strip() for item in guide[key])
        for key in ("objectives", "concepts", "checklist")
    )


def _build_study_guide_sections(guide: dict[str, Any]) -> list[dict[str, Any]]:
    existing_sections = guide.get("sections")
    if isinstance(guide.get("storyContext"), dict) and isinstance(existing_sections, list):
        story_kinds = {str(section.get("kind")) for section in existing_sections if isinstance(section, dict)}
        if {"preparation", "explanation", "examples", "self-check"}.issubset(story_kinds):
            return existing_sections
    example = guide.get("example") if isinstance(guide.get("example"), dict) else {}
    worked_examples = list(guide.get("workedExamples", []))
    if not worked_examples and example:
        worked_examples = [example]
    return [
        {
            "id": "exam-focus",
            "label": "考点",
            "title": "核心考点、公式结论与实际考法",
            "planningReason": str(guide.get("planningReason", "")),
            "examPoints": list(guide.get("examPoints", [])),
            "objectives": list(guide.get("objectives", [])),
            "sourceHighlights": list(guide.get("sourceHighlights", [])),
        },
        {
            "id": "method",
            "label": "讲解",
            "title": "逐个讲透定义、公式、条件和步骤",
            "examPoints": list(guide.get("examPoints", [])),
            "concepts": list(guide.get("concepts", [])),
        },
        {
            "id": "worked-example",
            "label": "例题",
            "title": "用具体题目完成方法迁移",
            "example": example,
            "workedExamples": worked_examples,
        },
        {
            "id": "self-check",
            "label": "自测",
            "title": "用覆盖本节考点的题目确认掌握",
            "checklist": list(guide.get("checklist", [])),
            "selfTestQuestionIds": list(guide.get("selfTestQuestionIds", [])),
        },
    ]


def _ensure_workspace_content_quality(workspace: dict[str, Any]) -> bool:
    changed = False
    points = [point for point in workspace.get("knowledgePoints", []) if isinstance(point, dict)]
    for task in workspace.get("tasks", []):
        if not isinstance(task, dict):
            continue
        if study_scheduler.is_orientation(task):
            # 导引任务的 studyGuide 是 orientation 专属结构，不走 examPoints 判定
            # 与 4 段式 sections 规范化，也不应被打"讲义不完整"警告。
            if task.pop("contentQualityWarning", None) is not None:
                changed = True
            continue
        guide = task.get("studyGuide")
        if isinstance(guide, dict) and "example" not in guide and isinstance(guide.get("workedExample"), dict):
            guide["example"] = guide["workedExample"]
            changed = True
        if not _complete_study_guide(task.get("studyGuide")):
            if task.get("contentQualityWarning") != "本节讲义不完整，请重新生成复习主线":
                task["contentQualityWarning"] = "本节讲义不完整，请重新生成复习主线"
                changed = True
            continue
        if task.pop("contentQualityWarning", None) is not None:
            changed = True
        guide = task.get("studyGuide")
        if isinstance(guide, dict):
            expected_sections = _build_study_guide_sections(guide)
            if guide.get("sections") != expected_sections:
                guide["sections"] = expected_sections
                changed = True

    # 模拟卷缺失或题型不完整时由通用 question-generation/repair 工作流处理。
    # 这里仅修复悬空的知识点引用，不再按任何具体课程注入静态题库。
    known_point_ids = {str(point.get("id", "")) for point in points}
    default_point_id = next(iter(known_point_ids), "diagnostic")
    for question in workspace.get("mockQuestions", []):
        if not isinstance(question, dict):
            continue
        if str(question.get("knowledgePointId", "")) not in known_point_ids:
            question["knowledgePointId"] = default_point_id
            changed = True

    if workspace.get("workspaceContentVersion") != WORKSPACE_CONTENT_VERSION:
        workspace["workspaceContentVersion"] = WORKSPACE_CONTENT_VERSION
        workspace["contentRefreshedAt"] = datetime.now().isoformat(timespec="seconds")
        changed = True
    return changed


def _workspace_is_planned(workspace: dict[str, Any]) -> bool:
    onboarding = workspace.get("onboarding")
    if not isinstance(onboarding, dict):
        return True
    return onboarding.get("status") == "planned"


def _clear_pre_plan_content(workspace: dict[str, Any]) -> None:
    workspace["knowledgePoints"] = []
    workspace["tasks"] = []
    workspace["practiceQuestions"] = []
    workspace["mockQuestions"] = []
    workspace["practiceAnswers"] = {}
    workspace["mockResult"] = None
    if workspace.get("onboarding", {}).get("status") == "draft":
        workspace["diagnosticQuestions"] = []


def _empty_course_workspace(
    materials: list[dict[str, Any]] | None = None,
    *,
    course: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # scan/_mark 属资料域缝合点，延迟 import 保持 study_service 打桩面。
    from .study_service import _mark_material_memory, scan_course_materials

    if not isinstance(course, dict):
        raise ValueError("创建课程学习空间必须提供课程信息")
    course_payload = course
    course_id = _validate_course_id(str(course_payload.get("id") or ""))
    current_materials = materials if materials is not None else scan_course_materials(course_id)
    course_name = str(course_payload["name"])
    target_score = int(course_payload.get("targetScore", 60))
    workspace: dict[str, Any] = {
        "course": course_payload,
        "assessmentProfile": {
            "summary": "请先在资料库导入课件、练习题、模拟卷或真题，再填写考试目标和考试形式。",
            "questionTypes": ["待填写"],
        },
        "diagnostic": {
            "estimatedScore": "未摸底",
            "message": "资料导入和课程信息填写完成后，AI 会先生成 10-15 分钟摸底测试。",
        },
        "knowledgePoints": [],
        "tasks": [],
        "practiceQuestions": [],
        "mockQuestions": [],
        "wrongAnswers": [],
        "note": f"## {course_name}考前笔记\n\n- 在摸底测试后，把自己的易错点和老师强调的重点补充到这里。",
        "messages": [
            {
                "id": f"{course_id}-draft-welcome",
                "role": "assistant",
                "content": f"{course_name}学习空间已建立。请先导入复习资料，再填写目标分数、复习时间、考试形式和备注，我会先做摸底，再初始化复习主线。",
                "createdAt": "刚刚",
            }
        ],
        "diagnosticQuestions": [],
        "onboarding": {
            "status": "draft",
            "courseName": course_name,
            "examDate": str(course_payload.get("examDate", "")),
            "targetScore": target_score,
            "targetText": f"保证 {target_score} 分",
            "dailyHours": float(course_payload.get("dailyHours", 2)),
            "days": _review_days_from_exam_date(course_payload.get("examDate")) or 3,
            "reviewCount": int(course_payload.get("reviewCount") or 0) or (_review_days_from_exam_date(course_payload.get("examDate")) or 3),
            "examFormat": "",
            "remarks": "",
            "createdAt": datetime.now().isoformat(timespec="seconds"),
        },
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "generationMode": "fallback",
        "workspaceContentVersion": WORKSPACE_CONTENT_VERSION,
    }
    _mark_material_memory(workspace, current_materials)
    return workspace


def create_empty_course_workspace(course_id: str) -> dict[str, Any]:
    from .study_service import save_workspace, scan_course_materials

    workspace = _empty_course_workspace(
        scan_course_materials(course_id),
        course={
            "id": course_id,
            "name": "未命名课程",
            "examDate": "待填写",
            "targetScore": 60,
            "dailyHours": 2,
            "progress": 0,
            "color": "#ff537f",
            "icon": "math",
        },
    )
    save_workspace(workspace, course_id)
    return workspace


def create_course_workspace(course: dict[str, Any]) -> dict[str, Any]:
    from .study_service import save_workspace

    course_id = _validate_course_id(str(course["id"]))
    workspace = _empty_course_workspace([], course=course)
    _course_material_directory(course_id).mkdir(parents=True, exist_ok=True)
    save_workspace(workspace, course_id)
    return workspace


def _reshuffle_unanswered_single_choice(workspace: dict[str, Any]) -> bool:
    """一次性迁移：重洗所有「未作答且未记错题」的单选题选项，让历史遗留的全 A 答案重新均匀分布。

    已作答（diagnosticAnswers/practiceAnswers/mockResult.answers）或已进错题的题保持原样，
    因为历史记录存的是选项索引，重洗会导致索引与选项位置错位。
    """
    answered: set[str] = set()
    for answer_key in ("diagnosticAnswers", "practiceAnswers"):
        value = workspace.get(answer_key)
        if isinstance(value, dict):
            answered.update(str(key) for key in value)
    mock_result = workspace.get("mockResult")
    if isinstance(mock_result, dict) and isinstance(mock_result.get("answers"), dict):
        answered.update(str(key) for key in mock_result["answers"])
    for item in workspace.get("wrongAnswers", []) or []:
        if isinstance(item, dict):
            answered.add(str(item.get("questionId", "")))
    changed = False
    for question_key in ("diagnosticQuestions", "practiceQuestions", "mockQuestions"):
        for question in workspace.get(question_key, []) or []:
            if not isinstance(question, dict):
                continue
            if str(question.get("id", "")) in answered:
                continue
            before = question.get("answerIndex")
            _shuffle_single_choice_options(question)
            if question.get("answerIndex") != before:
                changed = True
    return changed


def load_workspace(
    course_id: str,
    *,
    refresh_materials: bool = True,
) -> dict[str, Any]:
    # 缝合点：save/scan/_mark/_needs_refresh 可能被测试 patch study_service 命名空间，
    # 必须运行时读取（详见模块头注释）。
    from .study_service import (
        _mark_material_memory,
        _workspace_needs_material_refresh,
        save_workspace,
        scan_course_materials,
    )

    workspace_path = _workspace_path(course_id)
    if not workspace_path.exists():
        raise FileNotFoundError("课程学习空间尚未初始化")
    workspace = json.loads(workspace_path.read_text(encoding="utf-8"))
    changed = False
    if not isinstance(workspace.get("revision"), int):
        workspace["revision"] = 0
        changed = True
    if not isinstance(workspace.get("planRevision"), int):
        workspace["planRevision"] = int(workspace.get("revision", 0))
        changed = True
    if not isinstance(workspace.get("timeLog"), list):
        workspace["timeLog"] = []
        changed = True
    if not str(workspace.get("planStartDate", "")).strip():
        fallback_start = str(workspace.get("generatedAt", ""))[:10]
        workspace["planStartDate"] = fallback_start or datetime.now().date().isoformat()
        changed = True
    if refresh_materials and _workspace_needs_material_refresh(workspace):
        _mark_material_memory(workspace, scan_course_materials(course_id, workspace=workspace))
        changed = True
    elif not isinstance(workspace.get("materialMemory"), dict):
        _mark_material_memory(workspace, workspace.get("materials", []))
        changed = True
    if _workspace_is_planned(workspace):
        if _ensure_workspace_content_quality(workspace):
            changed = True
        if not workspace.get("optionShuffleMigrated"):
            if _reshuffle_unanswered_single_choice(workspace):
                changed = True
            workspace["optionShuffleMigrated"] = True
            changed = True
    else:
        _clear_pre_plan_content(workspace)
        changed = True
    if changed:
        save_workspace(workspace, course_id)
    return workspace


def _workspace_lock(course_id: str) -> threading.RLock:
    with _WORKSPACE_LOCKS_GUARD:
        return _WORKSPACE_LOCKS.setdefault(course_id, threading.RLock())


def _content_generation_lock(course_id: str) -> threading.Lock:
    with _CONTENT_GENERATION_LOCKS_GUARD:
        return _CONTENT_GENERATION_LOCKS.setdefault(course_id, threading.Lock())


def save_workspace(
    workspace: dict[str, Any],
    course_id: str | None = None,
    expected_revision: int | None = None,
) -> None:
    resolved_course_id = str(course_id or workspace.get("course", {}).get("id") or "")
    if not resolved_course_id:
        raise ValueError("保存课程学习空间必须提供 course_id")
    resolved_course_id = _validate_course_id(resolved_course_id)
    workspace_path = _workspace_path(resolved_course_id)
    with _workspace_lock(resolved_course_id):
        current_revision = 0
        current_plan_revision = 0
        current_tasks: list[dict[str, Any]] = []
        if workspace_path.exists():
            try:
                current = json.loads(workspace_path.read_text(encoding="utf-8"))
                current_revision = int(current.get("revision", 0))
                current_plan_revision = int(current.get("planRevision", current_revision))
                current_tasks = current.get("tasks", []) if isinstance(current.get("tasks"), list) else []
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                current_revision = 0
        if expected_revision is not None and current_revision != expected_revision:
            raise RuntimeError("学习空间已被其他操作更新，请刷新后重试")
        incoming_plan_revision = int(workspace.get("planRevision", current_plan_revision))
        tasks_changed = current_tasks != workspace.get("tasks", [])
        workspace["planRevision"] = max(current_plan_revision, incoming_plan_revision) + int(tasks_changed)
        workspace["revision"] = max(current_revision, int(workspace.get("revision", 0))) + 1
        _atomic_write_text(workspace_path, json.dumps(workspace, ensure_ascii=False, indent=2))


def load_mind_map(course_id: str) -> dict[str, Any]:
    from .study_service import load_workspace

    _validate_course_id(course_id)
    load_workspace(course_id, refresh_materials=False)
    mind_map_path = _mind_map_path(course_id)
    if not mind_map_path.exists():
        raise FileNotFoundError("课程知识地图尚未生成")
    mind_map = json.loads(mind_map_path.read_text(encoding="utf-8"))
    if not isinstance(mind_map, dict):
        raise ValueError("课程知识地图格式无效")
    return mind_map


def save_mind_map(mind_map: dict[str, Any], course_id: str) -> dict[str, Any]:
    from .study_service import load_workspace

    if not isinstance(mind_map, dict):
        raise ValueError("课程知识地图格式无效")
    _validate_course_id(course_id)
    workspace = load_workspace(course_id, refresh_materials=False)
    nodes = mind_map.get("nodes")
    edges = mind_map.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("课程知识地图必须包含 nodes 和 edges")
    normalized = {
        **mind_map,
        "version": int(mind_map.get("version", 1)),
        "courseId": course_id,
        "generatedAt": str(mind_map.get("generatedAt") or datetime.now().isoformat(timespec="seconds")),
        "sourceRevision": int(mind_map.get("sourceRevision", workspace.get("revision", 0))),
        "layout": "tree-right",
        "nodes": nodes,
        "edges": edges,
    }
    _atomic_write_text(_mind_map_path(course_id), json.dumps(normalized, ensure_ascii=False, indent=2))
    return normalized
