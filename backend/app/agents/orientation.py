from __future__ import annotations

import json
from typing import Any

from .checkpoint_contracts import orientation_guide_signature
from .workflow_types import JsonModelCall
from ..agent_runtime import get_latest_artifact, save_artifact
from .. import study_scheduler

# 第0天·复习导引任务的固定 id（幂等注入判重用）。
ORIENTATION_TASK_ID = "task-day0-orientation"


def _orientation_guide_issues(guide: Any, expected_days: int) -> list[str]:
    """校验导引内容结构完整性，返回问题列表（空列表 = 通过）。"""
    if not isinstance(guide, dict):
        return ["导引内容不是对象"]
    issues: list[str] = []
    overview = str(guide.get("overview", "")).strip()
    if len(overview) < 120:
        issues.append("overview 过短（需 ≥120 字）")
    phases = guide.get("phases")
    if not isinstance(phases, list) or len(phases) < 2:
        issues.append("phases 至少 2 个阶段")
    else:
        for phase in phases:
            if not isinstance(phase, dict) or not str(phase.get("title", "")).strip() or not str(phase.get("goal", "")).strip():
                issues.append("phase 缺少 title 或 goal")
                break
    layers = guide.get("dependencyLayers")
    if not isinstance(layers, list) or not layers:
        issues.append("dependencyLayers 至少 1 层")
    else:
        for layer in layers:
            if not isinstance(layer, dict) or not isinstance(layer.get("knowledgePoints"), list) or not layer["knowledgePoints"]:
                issues.append("dependencyLayer 缺少 knowledgePoints")
                break
    method = guide.get("method")
    if not isinstance(method, list) or len([m for m in method if str(m).strip()]) < 3:
        issues.append("method 至少 3 条")
    milestones = guide.get("milestones")
    if not isinstance(milestones, list) or len(milestones) < 2:
        issues.append("milestones 至少 2 项")
    else:
        for milestone in milestones:
            day = milestone.get("day") if isinstance(milestone, dict) else None
            if not isinstance(day, int) or not 1 <= day <= max(1, expected_days):
                issues.append(f"milestone day 越界：{day}")
                break
    checklist = guide.get("checklist")
    if not isinstance(checklist, list) or len([c for c in checklist if str(c).strip()]) < 4:
        issues.append("checklist 至少 4 条")
    return issues


def _backup_orientation_guide(
    course: dict[str, Any],
    onboarding: dict[str, Any],
    modules: list[dict[str, Any]],
    knowledge_points: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    """LLM 不可用时的确定性导引兜底：直接由 tasks/依赖图拼装，保证结构完整。"""
    course_name = str(course.get("name", "本课程")) if isinstance(course, dict) else "本课程"
    days = max(1, int(onboarding.get("days", 1)) if isinstance(onboarding, dict) else 1)
    day_tasks = sorted(
        [t for t in tasks if isinstance(t, dict) and isinstance(t.get("day"), int)],
        key=lambda t: (t["day"], int(t.get("order", 999))),
    )
    max_day = max((t["day"] for t in day_tasks), default=days)

    # 三等分为基础建构 / 主线推进 / 综合冲刺。
    third = max(1, (max_day + 2) // 3)
    boundaries = [(1, third), (third + 1, 2 * third), (2 * third + 1, max_day)]
    phase_names = ["基础建构", "主线推进", "综合冲刺"]
    phases = []
    for (start, end), name in zip(boundaries, phase_names):
        titles = [str(t.get("title", "")) for t in day_tasks if start <= t["day"] <= end][:4]
        phases.append(
            {
                "title": f"{name}（第{start}-{end}天）",
                "dayRange": f"第{start}-{end}天",
                "goal": f"完成{name}阶段的学习单元：{'、'.join(titles) if titles else '按主线任务推进'}",
                "focus": titles,
            }
        )

    # 依赖分层直接用调度器的拓扑层（空图时退化为按出现顺序一层）。
    kp_rank = study_scheduler.topological_rank(knowledge_points, modules)
    layer_names = {1: "第1层·地基", 2: "第2层·进阶", 3: "第3层·深入", 4: "第4层·综合"}
    by_layer: dict[int, list[str]] = {}
    for point in knowledge_points:
        if not isinstance(point, dict):
            continue
        level = int(kp_rank.get(str(point.get("id", "")), 1))
        by_layer.setdefault(level, []).append(str(point.get("name", "")))
    dependency_layers = [
        {
            "level": level,
            "title": layer_names.get(level, f"第{level}层"),
            "knowledgePoints": names,
            "rationale": "先掌握本层知识点，才能稳定进入下一层的学习" if level > 1 else "入门概念，无前置依赖，从这里开始",
        }
        for level, names in sorted(by_layer.items())
    ]
    if not dependency_layers:
        dependency_layers = [
            {
                "level": 1,
                "title": "第1层·地基",
                "knowledgePoints": [str(p.get("name", "")) for p in knowledge_points[:6] if isinstance(p, dict)],
                "rationale": "按主线顺序依次掌握",
            }
        ]

    overview = (
        f"《{course_name}》共 {days} 天复习，主线按「{phases[0]['title'].split('（')[0]} → "
        f"{phases[1]['title'].split('（')[0]} → {phases[2]['title'].split('（')[0]}」推进："
        f"先打牢无前置依赖的地基概念，再沿知识点依赖链逐层深入，最后做跨章节综合与闭卷输出。"
        f"每天按主线顺序学习即可，调度器已保证每个任务的前置知识都排在它之前；"
        f"遇到卡壳先回到对应层的前置知识点，不要跳层硬啃。"
    )
    return {
        "overview": overview,
        "phases": phases,
        "dependencyLayers": dependency_layers,
        "method": [
            "每天先过一遍当日任务清单，明确本日要产出的东西（对照表/流程图/限时练习记录）",
            "学新知识点前先确认其前置知识点已掌握，卡壳就回看上一层",
            "每完成一个学习单元就做配套自测，错题当场标注错因类型",
            "每 3 天做一次闭卷回顾，把讲不出来的知识点标回薄弱",
        ],
        "milestones": [
            {"day": boundaries[0][1], "title": "基础建构完成", "criteria": "地基层知识点能独立复述核心定义"},
            {"day": boundaries[1][1], "title": "主线推进完成", "criteria": "进阶层过程题能逐步写清步骤"},
            {"day": max_day, "title": "综合冲刺完成", "criteria": "综合卷得分率达到目标，错题全部标注错因"},
        ],
        "checklist": [
            "已了解整门课的阶段划分和依赖分层",
            "已确认每天可用的复习时段",
            "已明确四大失分点/薄弱点将在哪些天集中处理",
            "已准备好错题本或错因记录方式",
        ],
    }


def build_orientation_guide(
    model_json: JsonModelCall,
    *,
    course_id: str,
    course: dict[str, Any],
    onboarding: dict[str, Any],
    review_plan: str,
    course_prompt: str,
    modules: list[dict[str, Any]],
    knowledge_points: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    assessment_profile: dict[str, Any],
    run_id: str = "",
) -> tuple[dict[str, Any], bool]:
    """生成第0天·复习导引内容；返回 (orientation 结构, 是否降级)。

    checkpoint 命中或 LLM 校验通过 → 正常结构；LLM 失败 → 确定性兜底（degraded=True，
    不写 checkpoint），绝不抛异常中断主流程。
    """
    expected_days = max(1, int(onboarding.get("days", 1)) if isinstance(onboarding, dict) else 1)
    signature = orientation_guide_signature(
        modules=modules,
        knowledge_points=knowledge_points,
        review_plan=review_plan,
        days=expected_days,
    )
    cached = get_latest_artifact(course_id, "orientation_guide_checkpoint")
    cached_content = cached.get("content", {}) if cached else {}
    if cached_content.get("signature") == signature and not _orientation_guide_issues(cached_content.get("guide"), expected_days):
        return cached_content["guide"], False

    orientation_prompt = """
你是 Course Orientation Agent。根据输入中的复习计划、模块、知识点依赖链和课程画像，生成一份「第0天·复习导引」，帮学习者在开始逐知识点学习前建立整门课程的整体复习概念。这是计划型内容，不是知识点讲解。
只返回 JSON：
{
 "orientation":{
   "overview":"200字左右的课程复习框架总述：这门课分几个阶段、主线怎么走、薄弱点在哪、为什么按这个顺序学",
   "phases":[{"title":"阶段名（如 基础建构）","dayRange":"第X-Y天","goal":"该阶段要达成什么","focus":["该阶段覆盖的代表性知识点或任务主题"]}],
   "dependencyLayers":[{"level":1,"title":"第1层·地基","knowledgePoints":["知识点名称"],"rationale":"为什么这一层要先学，它支撑了哪些后续内容"}],
   "method":["3-5条针对这门课的具体学习方法，不要通用套话"],
   "milestones":[{"day":整数,"title":"里程碑名","criteria":"达成标准"}],
   "checklist":["4-6条开始正式复习前的检查项"]
 }
}
要求：phases 覆盖全部复习天数且不重叠；dependencyLayers 按真实前置依赖分层，第 1 层必须是无前置的知识点，层次 level 从 1 递增；milestones 的 day 在 1 到总天数之间；overview、goal、rationale 等用户可见文本不要写来源、出处、资料依据或参考。
"""
    orientation_input = {
        "course": course,
        "onboarding": onboarding,
        "reviewPlan": review_plan,
        "modules": modules,
        "knowledgePoints": [
            {k: point.get(k) for k in ("id", "name", "prerequisites", "difficulty", "weight", "mastery")}
            for point in knowledge_points
            if isinstance(point, dict)
        ],
        "taskOutline": [
            {"day": t.get("day"), "title": t.get("title"), "knowledgePointId": t.get("knowledgePointId")}
            for t in tasks
            if isinstance(t, dict)
        ],
        "assessmentProfile": assessment_profile,
    }
    guide: dict[str, Any] | None = None
    try:
        parsed = model_json(
            orientation_prompt,
            json.dumps(orientation_input, ensure_ascii=False),
            course_prompt,
        )
        candidate = parsed.get("orientation") if isinstance(parsed, dict) else None
        issues = _orientation_guide_issues(candidate, expected_days)
        if not issues:
            guide = candidate
        else:
            parsed = model_json(
                orientation_prompt + "\n请修复 orientationIssues 中的全部问题，仍只返回完整 orientation JSON。",
                json.dumps({**orientation_input, "orientationIssues": issues}, ensure_ascii=False),
                course_prompt,
            )
            candidate = parsed.get("orientation") if isinstance(parsed, dict) else None
            if not _orientation_guide_issues(candidate, expected_days):
                guide = candidate
    except Exception:
        guide = None

    if guide is None:
        return _backup_orientation_guide(course, onboarding, modules, knowledge_points, tasks), True
    save_artifact(
        course_id,
        "orientation_guide_checkpoint",
        {"signature": signature, "guide": guide},
        status="checkpoint",
        source_run_id=run_id,
    )
    return guide, False


def _make_orientation_task(course_id: str, guide: dict[str, Any]) -> dict[str, Any]:
    """构造第0天·复习导引任务 dict（day=0/order=0，studyGuide 为 orientation 专属结构）。"""
    return {
        "id": ORIENTATION_TASK_ID,
        "courseId": course_id,
        "kind": "orientation",
        "day": 0,
        "order": 0,
        "title": "第0天·复习导引",
        "description": "用 15 分钟建立整门课程的复习框架：阶段划分、知识点依赖分层、学习方法与里程碑，再开始第 1 天的正式复习。",
        "source": "复习计划与知识点依赖链",
        "duration": 15,
        "progress": 0,
        "weight": 0,
        "knowledgePointId": "",
        "status": "pending",
        "priority": "medium",
        "studyGuide": {"orientation": guide},
    }
