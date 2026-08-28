"""复习计划域（阶段2-6 从 study_service.py 抽取）。

职责：复习总计划的 AI 维护（maintain_review_plan）、每日进度纯函数
（build_daily_progress）、学习时长记录与删除（record_time /
delete_time_entry）、每日顺延/减负提案（rebalance_daily_plan）、
按新参数重排复习主线提案（replan_review_mainline）、工作台任务/
错题/笔记的手动更新入口（update_workspace_state）。

依赖方向：review_plan → study_scheduler / agent_runtime /
agents.tools，禁止模块级 import study_service（成环）。

与 practice.py 相同的缝合点约定：load_workspace / save_workspace /
get_course_prompt / _read_strategy_document / _write_strategy_document /
_model_completion / _extract_json / build_model_messages /
_review_session_days 属于跨域符号——测试惯用
monkeypatch.setattr(study_service, ...) 打桩，故本模块在函数体内
延迟 import study_service，调用时读取其（可能已被测试替换的）命名空间。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from . import study_scheduler
from .agent_runtime import create_adjustment_proposal
from .agents.tools import apply_operations_to_copy


def maintain_review_plan(course_id: str, event: str) -> None:
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    from .study_service import (
        _extract_json,
        _model_completion,
        _read_strategy_document,
        _write_strategy_document,
        build_model_messages,
        get_course_prompt,
        load_workspace,
        save_workspace,
    )

    workspace = load_workspace(course_id, refresh_materials=False)
    strategy_documents = workspace.get("strategyDocuments", {})
    review_metadata = strategy_documents.get("reviewPlan", {})
    base_version = int(review_metadata.get("version", 0))
    current_plan = _read_strategy_document(course_id, "reviewPlan")
    if strategy_documents.get("status") != "approved" or not current_plan:
        return

    compact_state = {
        "event": event,
        "course": workspace.get("course", {}),
        "onboarding": workspace.get("onboarding", {}),
        "modules": workspace.get("modules", []),
        "knowledgePoints": workspace.get("knowledgePoints", []),
        # tasks 全量序列化可达 ~2MB（studyGuide 全文），上游网关对超大请求体
        # 直接回 HTTP 502 且重试无济于事——只送调度相关字段，压缩到 KB 级。
        "tasks": [
            {
                key: task.get(key)
                for key in (
                    "id",
                    "day",
                    "order",
                    "title",
                    "status",
                    "duration",
                    "priority",
                    "knowledgePointId",
                )
            }
            for task in workspace.get("tasks", [])
            if isinstance(task, dict)
        ],
        "wrongAnswers": [
            {
                key: answer.get(key)
                for key in ("question", "userAnswer", "correctAnswer", "knowledgePointId", "wrongCount")
                if answer.get(key) is not None
            }
            for answer in workspace.get("wrongAnswers", [])
            if isinstance(answer, dict)
        ],
        "materialMemory": workspace.get("materialMemory", {}),
        "note": workspace.get("note", ""),
    }
    task_prompt = """
你负责维护课程的“速通复习总计划”文档。根据最新学习状态和本次事件，更新计划，使其忠实反映已完成任务、当前薄弱点、剩余时间和下一阶段策略。
若输入的 modules/任务排布显示复习主线已重排（模块顺序或组成变化），必须让计划中的“复习主线”与新的模块顺序完全一致，旧主线表述全部改写。
只更新复习计划，不修改课程总 Prompt，也不要声称修改了后端任务。保留既有 Markdown 章节结构，但把“资料依据/来源/出处/参考”类展示改写为复习重点、安排思路或直接删除。
只返回 JSON：{"reviewPlanMarkdown":"完整新版 Markdown","changeSummary":"一句话变更摘要"}
"""
    try:
        parsed = _extract_json(
            _model_completion(
                build_model_messages(
                    task_prompt,
                    (
                        f"【当前复习计划】\n{current_plan}\n\n"
                        f"【最新学习状态】\n{json.dumps(compact_state, ensure_ascii=False, indent=2)}"
                    ),
                    course_prompt=get_course_prompt(course_id),
                ),
                json_mode=True,
            )
        )
        next_plan = str(parsed.get("reviewPlanMarkdown", ""))
        change_summary = str(parsed.get("changeSummary", "")).strip() or f"根据{event}更新复习计划"
        latest_workspace = load_workspace(course_id, refresh_materials=False)
        latest_documents = latest_workspace.get("strategyDocuments", {})
        if int(latest_documents.get("reviewPlan", {}).get("version", 0)) != base_version:
            latest_documents["maintenancePending"] = True
            latest_documents["maintenanceError"] = "复习计划在维护期间已更新，本次结果未覆盖新版本"
            save_workspace(latest_workspace, course_id)
            return
        _write_strategy_document(
            latest_workspace,
            course_id,
            "reviewPlan",
            next_plan,
            updated_by="ai",
            change_summary=change_summary,
        )
        latest_documents["maintenancePending"] = False
        latest_documents["maintenanceError"] = ""
        latest_documents["lastMaintenanceEvent"] = event
        save_workspace(latest_workspace, course_id)
    except Exception as error:
        latest_workspace = load_workspace(course_id, refresh_materials=False)
        latest_documents = latest_workspace.setdefault("strategyDocuments", {})
        latest_documents["maintenancePending"] = False
        latest_documents["maintenanceError"] = str(error)
        save_workspace(latest_workspace, course_id)


def _parse_plan_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def build_daily_progress(
    workspace: dict[str, Any],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """纯函数：根据 planStartDate + timeLog + tasks 算出今日进度与顺延候选。"""
    current_day = today or datetime.now().date()
    tasks = [task for task in workspace.get("tasks", []) if isinstance(task, dict)]
    max_day = max((int(task.get("day", 0)) for task in tasks), default=1)

    start_date = _parse_plan_date(workspace.get("planStartDate"))
    if start_date is None:
        today_day = 1
    else:
        today_day = max(1, min(max_day, (current_day - start_date).days + 1))

    today_iso = current_day.isoformat()
    planned_today = sum(
        int(task.get("duration", 0))
        for task in tasks
        if int(task.get("day", 0)) == today_day
    )
    spent_today = sum(
        int(entry.get("minutes", 0))
        for entry in workspace.get("timeLog", [])
        if isinstance(entry, dict) and str(entry.get("date", "")) == today_iso
    )
    overdue_tasks = [
        {
            "id": task.get("id"),
            "title": task.get("title"),
            "day": task.get("day"),
            "duration": task.get("duration"),
            "priority": task.get("priority"),
            "status": task.get("status"),
        }
        for task in tasks
        if int(task.get("day", 0)) < today_day
        and task.get("status") != "completed"
        # 导引任务 day=0 恒小于 today_day，但不参与逾期判定（随时可看，不算逾期）。
        and not study_scheduler.is_orientation(task)
    ]
    remaining = max(0, planned_today - spent_today)
    over_budget = planned_today > 0 and spent_today > planned_today
    return {
        "date": today_iso,
        "todayDay": today_day,
        "maxDay": max_day,
        "plannedToday": planned_today,
        "spentToday": spent_today,
        "remaining": remaining,
        "overBudget": over_budget,
        "overdue": overdue_tasks,
    }


def record_time(
    course_id: str,
    *,
    task_id: str | None,
    minutes: int,
    target_date: str | None = None,
    note: str = "",
    client_entry_id: str | None = None,
) -> dict[str, Any]:
    if minutes <= 0 or minutes > 24 * 60:
        raise ValueError("学习时长必须在 1-1440 分钟之间")
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    from .study_service import build_daily_progress as _bdp, load_workspace, save_workspace

    workspace = load_workspace(course_id, refresh_materials=False)
    entries = workspace.get("timeLog")
    if not isinstance(entries, list):
        entries = []
        workspace["timeLog"] = entries
    normalized_client_entry_id = (client_entry_id or "").strip()
    if normalized_client_entry_id:
        existing_entry = next(
            (entry for entry in entries if isinstance(entry, dict) and entry.get("id") == normalized_client_entry_id),
            None,
        )
        if existing_entry is not None:
            return {"entry": existing_entry, "dailyProgress": _bdp(workspace)}
    entry = {
        "id": normalized_client_entry_id or f"log-{int(datetime.now().timestamp() * 1000)}",
        "taskId": (task_id or "").strip(),
        "date": (target_date or datetime.now().date().isoformat()),
        "minutes": int(minutes),
        "note": (note or "").strip()[:200],
        "createdAt": datetime.now().isoformat(timespec="seconds"),
    }
    entries.append(entry)
    save_workspace(workspace, course_id)
    return {"entry": entry, "dailyProgress": _bdp(workspace)}


def delete_time_entry(course_id: str, entry_id: str) -> dict[str, Any]:
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    from .study_service import build_daily_progress as _bdp, load_workspace, save_workspace

    workspace = load_workspace(course_id, refresh_materials=False)
    entries = workspace.get("timeLog", [])
    workspace["timeLog"] = [
        item for item in entries if isinstance(item, dict) and item.get("id") != entry_id
    ]
    save_workspace(workspace, course_id)
    return {"dailyProgress": _bdp(workspace)}


def rebalance_daily_plan(course_id: str, event: str = "每日时间核对") -> None:
    """根据今日实际耗时与未完成任务，生成「顺延/减负」提案，等待用户确认。"""
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    from .study_service import (
        _extract_json,
        _model_completion,
        build_model_messages,
        get_course_prompt,
        load_workspace,
        save_workspace,
    )

    workspace = load_workspace(course_id, refresh_materials=False)
    progress = build_daily_progress(workspace)
    if not progress["overdue"] and not progress["overBudget"]:
        return

    compact_state = {
        "event": event,
        "dailyProgress": progress,
        "course": workspace.get("course", {}),
        "onboarding": workspace.get("onboarding", {}),
        "tasks": [
            {
                "id": task.get("id"),
                "title": task.get("title"),
                "day": task.get("day"),
                "order": task.get("order"),
                "duration": task.get("duration"),
                "status": task.get("status"),
                "priority": task.get("priority"),
            }
            for task in workspace.get("tasks", [])
            if isinstance(task, dict) and not study_scheduler.is_orientation(task)
        ],
    }
    task_prompt = """
你负责根据“今日实际学习时长”和“任务完成情况”滚动调整复习计划，只生成可执行的调整操作列表，不直接改写计划文档。
判定规则：
1. dailyProgress.overdue 里（day < 今天且未完成）的任务，必须用 move_task 顺延到今天之后、当日 duration 合计更接近每日目标的天数；若后续每天都已满，再追加一天。
2. dailyProgress.overBudget=true（今天已学超过当天计划）时，对后续天数里 priority 较低的任务用 change_duration 适度减负，或用 move_task 把后续高优任务提前。
3. 不得删除任务，不得改动 studyGuide；operations 只允许 move_task / change_duration / change_priority。
4. move_task 的 day 取值 1-30、order 取值 1-100；change_duration 的 minutes 必须 5-720。
只返回 JSON：{"title":"一句话标题","reason":"为什么这么调","impact":"调整后效果","operations":[{"type":"move_task|change_duration|change_priority","task_id":"...","day":整数,"order":整数,"minutes":整数,"priority":"high|medium|low"}]}
operations 至少 1 条、最多 12 条；确实没有合理调整时返回 operations=[]。
"""
    try:
        parsed = _extract_json(
            _model_completion(
                build_model_messages(
                    task_prompt,
                    json.dumps(compact_state, ensure_ascii=False, indent=2),
                    course_prompt=get_course_prompt(course_id),
                ),
                json_mode=True,
            )
        )
    except Exception:
        return

    operations = parsed.get("operations")
    if not isinstance(operations, list):
        return
    cleaned = [
        op for op in operations
        if isinstance(op, dict) and op.get("task_id") and op.get("type") in {"move_task", "change_duration", "change_priority"}
    ]
    if not cleaned:
        return

    latest_workspace = load_workspace(course_id, refresh_materials=False)
    try:
        after_tasks = apply_operations_to_copy(latest_workspace, cleaned)
    except Exception:
        return

    def _summary(tasks: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "totalMinutes": sum(int(t.get("duration", 0)) for t in tasks),
            "tasks": [
                {
                    "id": t.get("id"),
                    "day": t.get("day"),
                    "duration": t.get("duration"),
                    "status": t.get("status"),
                }
                for t in tasks
            ],
        }

    create_adjustment_proposal(
        course_id,
        base_revision=int(latest_workspace.get("planRevision", 0)),
        title=str(parsed.get("title", "每日计划滚动调整")).strip()[:200] or "每日计划滚动调整",
        reason=str(parsed.get("reason", "")).strip()[:2000],
        impact=str(parsed.get("impact", "")).strip()[:2000],
        operations=cleaned,
        before=_summary(latest_workspace.get("tasks", [])),
        after=_summary(after_tasks),
        source_run_id="",
    )


def replan_review_mainline(
    course_id: str,
    *,
    new_exam_date: str,
    new_days: int,
    new_daily_hours: float,
) -> dict[str, Any]:
    """按新的考试日期/复习天数/每日时长重新编排复习主线，生成携带新参数的 adjustment_proposal。

    参数不在此处落地，待用户「采纳」时由 apply_proposal 写入；「忽略」则参数与 tasks 都不动。
    失败抛 RuntimeError（同步端点，用户在等），由路由层映射为 502。
    """
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    from .study_service import (
        _extract_json,
        _model_completion,
        build_model_messages,
        get_course_prompt,
        load_workspace,
    )

    workspace = load_workspace(course_id, refresh_materials=False)
    progress = build_daily_progress(workspace)
    today_day = int(progress["todayDay"])
    new_budget = max(5, int(round(new_daily_hours * 60)))
    upper_day = max(today_day, new_days)  # new_days < today_day 时的兜底区间右端

    all_tasks = [task for task in workspace.get("tasks", []) if isinstance(task, dict)]
    movable_ids = {
        str(task.get("id"))
        for task in all_tasks
        if task.get("status") != "completed" and not study_scheduler.is_orientation(task)
    }

    compact_state = {
        "event": "用户调整复习参数后重新编排",
        "todayDay": today_day,
        "newDays": new_days,
        "newDailyBudgetMinutes": new_budget,
        "effectiveRange": [today_day, upper_day],
        "course": {
            **workspace.get("course", {}),
            "examDate": new_exam_date,
            "dailyHours": new_daily_hours,
        },
        "onboarding": {
            **(workspace.get("onboarding") or {}),
            "examDate": new_exam_date,
            "days": new_days,
            "dailyHours": new_daily_hours,
        },
        "movableTasks": [
            {
                "id": task.get("id"),
                "title": task.get("title"),
                "day": task.get("day"),
                "order": task.get("order"),
                "duration": task.get("duration"),
                "status": task.get("status"),
                "priority": task.get("priority"),
                "knowledgePointId": task.get("knowledgePointId"),
                "weight": task.get("weight"),
            }
            for task in all_tasks
            if str(task.get("id")) in movable_ids
        ],
        "completedTaskSummary": {
            "count": sum(1 for task in all_tasks if task.get("status") == "completed"),
            "totalMinutes": sum(
                int(task.get("duration", 0))
                for task in all_tasks
                if task.get("status") == "completed"
            ),
        },
    }

    task_prompt = """
你负责根据用户调整后的「考试日期 / 复习天数 / 每日复习时间」重新编排复习主线，只生成可执行的操作列表，不直接改写计划文档。
核心约束（必须严格遵守）：
1. status == "completed" 的任务视为已完成，绝对禁止改动（不能 move，也不能改 duration/priority）；你只能操作 movableTasks 列表里出现的任务。
2. 只允许输出 move_task / change_duration / change_priority 三种操作；禁止 remove_task，禁止删除任何已生成的 studyGuide 或练习题。
3. 所有被移动任务的 day 必须落在 effectiveRange 区间内（含端点）；day 小于 todayDay 的未完成任务必须顺延到 todayDay 及之后。
4. 目标：让 [todayDay, newDays] 区间内每一天未完成任务的 duration 合计尽量落在 newDailyBudgetMinutes 的 0.8 ~ 1.0 倍之间；priority 较高的任务优先排在更靠近 todayDay 的天数，保持知识点的先后与难度递进。
5. 优先压缩而非删除：当可用容量不足时，用 change_duration 适度缩减 priority 较低任务的时长（不得低于 5 分钟），或用 change_priority 调整权重让重要任务占据有效容量；宁可让个别日子的合计略超 newDailyBudgetMinutes，也不要删除任何任务。
6. 若 newDays 小于 todayDay（考试已临近），把剩余未完成任务集中到 effectiveRange 区间，并在 reason 中明确说明这些日子可能显著超额、建议用户适当提高每日时长或接受高强度冲刺。
字段约束：move_task 的 day 取值 1-30、order 取值 1-100；change_duration 的 minutes 必须 5-720；change_priority 的 priority 取值 high|medium|low。
只返回 JSON：{"title":"一句话标题","reason":"为什么这么重排","impact":"重排后效果（每天负载变化、是否有日子超额）","operations":[{"type":"move_task|change_duration|change_priority","task_id":"...","day":整数,"order":整数,"minutes":整数,"priority":"high|medium|low"}]}
operations 至少 1 条；确实无需调整时返回 operations=[]。
"""
    try:
        parsed = _extract_json(
            _model_completion(
                build_model_messages(
                    task_prompt,
                    json.dumps(compact_state, ensure_ascii=False, indent=2),
                    course_prompt=get_course_prompt(course_id),
                ),
                json_mode=True,
            )
        )
    except Exception as error:
        raise RuntimeError(f"AI 重新编排失败：{error}") from error

    operations = parsed.get("operations")
    if not isinstance(operations, list):
        raise RuntimeError("AI 返回的操作列表格式无效")

    # 清洗：类型白名单 + task_id 必须在未完成集合里（防止 LLM 误改已完成任务）
    cleaned = [
        operation
        for operation in operations
        if isinstance(operation, dict)
        and operation.get("task_id")
        and str(operation.get("task_id")) in movable_ids
        and operation.get("type") in {"move_task", "change_duration", "change_priority"}
    ]
    if not cleaned:
        raise RuntimeError("AI 未给出任何有效重排操作，请稍后重试或调整参数")

    latest_workspace = load_workspace(course_id, refresh_materials=False)
    try:
        after_tasks = apply_operations_to_copy(latest_workspace, cleaned)
    except ValueError as error:
        raise RuntimeError(f"重排操作非法：{error}") from error

    def _summary(tasks: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "totalMinutes": sum(int(task.get("duration", 0)) for task in tasks),
            "tasks": [
                {
                    "id": task.get("id"),
                    "day": task.get("day"),
                    "duration": task.get("duration"),
                    "status": task.get("status"),
                }
                for task in tasks
            ],
        }

    proposal = create_adjustment_proposal(
        course_id,
        base_revision=int(latest_workspace.get("planRevision", 0)),
        title=str(parsed.get("title", "按新参数重新编排复习主线")).strip()[:200]
        or "按新参数重新编排复习主线",
        reason=str(parsed.get("reason", "")).strip()[:2000],
        impact=str(parsed.get("impact", "")).strip()[:2000],
        operations=cleaned,
        before=_summary(latest_workspace.get("tasks", [])),
        after=_summary(after_tasks),
        source_run_id="",
        params={
            "examDate": new_exam_date,
            "days": new_days,
            "dailyHours": new_daily_hours,
        },
    )
    return proposal

def update_workspace_state(    *,
    tasks: list[dict[str, Any]] | None = None,
    wrong_answers: list[dict[str, Any]] | None = None,
    note: str | None = None,
    course_id: str,
) -> dict[str, Any]:
    workspace = load_workspace(course_id, refresh_materials=False)
    previous_tasks = list(workspace.get("tasks", []))
    if tasks is not None:
        # 手动调整后的 DAG 修复：违规 pending 任务顺延到前置之后，修复+警告放行（不硬拒）。
        onboarding_cfg = workspace.get("onboarding") or {}
        reconciled_tasks, scheduling_warnings = study_scheduler.enforce_dag_order(
            tasks,
            workspace.get("knowledgePoints", []),
            session_days=_review_session_days(
                int(onboarding_cfg.get("days") or 0),
                int(onboarding_cfg.get("reviewCount") or 0),
            ),
            daily_minutes=round(float(onboarding_cfg.get("dailyHours") or 0) * 60) or 120,
        )
        workspace["tasks"] = reconciled_tasks
        workspace["schedulingWarnings"] = scheduling_warnings
        record_review_progress(course_id, previous_tasks, reconciled_tasks)
    if wrong_answers is not None:
        workspace["wrongAnswers"] = wrong_answers
    if note is not None:
        workspace["note"] = note
    save_workspace(workspace, course_id)
    return workspace