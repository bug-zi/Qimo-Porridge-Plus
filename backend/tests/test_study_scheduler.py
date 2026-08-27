"""study_scheduler 纯函数调度器的单元测试。

运行：cd backend && .venv\\Scripts\\python -m pytest tests -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import study_scheduler


def kp(pid, name=None, *, weight=10, mastery=50, difficulty=3, prereqs=None, module="m-1"):
    return {
        "id": pid,
        "name": name or pid,
        "weight": weight,
        "mastery": mastery,
        "difficulty": difficulty,
        "prerequisites": list(prereqs or []),
        "moduleId": module,
    }


def task(tid, kp_id, *, day=1, order=1, duration=60, status="pending", priority="medium", kind=None):
    return {
        "id": tid,
        "knowledgePointId": kp_id,
        "title": f"任务{tid}",
        "day": day,
        "order": order,
        "duration": duration,
        "status": status,
        "priority": priority,
        "weight": 10,
        **({"kind": kind} if kind else {}),
    }


def orientation_task(course_id="test-course"):
    from app.agents.workflow import ORIENTATION_TASK_ID, _make_orientation_task

    guide = {
        "overview": "overview" * 40,
        "phases": [
            {"title": "基础", "dayRange": "第1-2天", "goal": "打基础", "focus": ["概念"]},
            {"title": "冲刺", "dayRange": "第3-4天", "goal": "综合练习"},
        ],
        "dependencyLayers": [
            {"level": 1, "title": "入口层", "knowledgePoints": ["基础概念"], "rationale": "无前置"},
        ],
        "method": ["先框架后细节", "每天自测", "错题当天归档"],
        "milestones": [
            {"day": 2, "title": "基础过关", "criteria": "自测正确率≥60%"},
            {"day": 4, "title": "全真模拟", "criteria": "完成一套模拟卷"},
        ],
        "checklist": ["确认考试时间", "备好资料", "规划每日时段", "建立错题本"],
    }
    return _make_orientation_task(course_id, guide), ORIENTATION_TASK_ID


# ---------- sanitize_dependencies ----------

def test_sanitize_strips_self_unknown_and_duplicates():
    points = [
        kp("a", prereqs=["a", "ghost", "b", "b", ""]),
        kp("b"),
    ]
    warnings = study_scheduler.sanitize_dependencies(points)
    assert points[0]["prerequisites"] == ["b"]
    assert warnings == []


def test_sanitize_clamps_difficulty():
    points = [kp("a", difficulty=99), kp("b", difficulty=-2), kp("c", difficulty="x")]
    study_scheduler.sanitize_dependencies(points)
    assert [p["difficulty"] for p in points] == [5, 1, 3]


def test_sanitize_breaks_cycle_at_lowest_weight_target():
    # 三节点环 a→b→c→a（prereq 方向：a 依赖 b，b 依赖 c，c 依赖 a）。
    # c 的 weight 最低 → 断掉指向 c 的边，即 a 的 prerequisites 里的 "c" 被移除。
    points = [
        kp("a", weight=20, prereqs=["b"]),
        kp("b", weight=15, prereqs=["c"]),
        kp("c", weight=5, prereqs=["a"]),
    ]
    warnings = study_scheduler.sanitize_dependencies(points)
    prereq_map = {p["id"]: p["prerequisites"] for p in points}
    # 无环判定：再跑一次 _find_cycle 必须为 None。
    assert study_scheduler._find_cycle(points) is None
    assert any("环" in w for w in warnings)
    # 断掉的应是指向最低 weight 目标（c）的那条边。
    assert "c" not in prereq_map["a"]


def test_sanitize_is_idempotent():
    points = [kp("a", prereqs=["b"]), kp("b", prereqs=["a"])]
    study_scheduler.sanitize_dependencies(points)
    snapshot = copy.deepcopy(points)
    study_scheduler.sanitize_dependencies(points)
    assert points == snapshot


# ---------- topological_rank ----------

def test_topological_linear_chain():
    points = [kp("c", prereqs=["b"]), kp("b", prereqs=["a"]), kp("a", difficulty=1)]
    rank = study_scheduler.topological_rank(points)
    assert rank["a"] < rank["b"] < rank["c"]


def test_topological_diamond():
    points = [
        kp("a", difficulty=1),
        kp("b", prereqs=["a"], difficulty=2),
        kp("c", prereqs=["a"], difficulty=1),
        kp("d", prereqs=["b", "c"]),
    ]
    rank = study_scheduler.topological_rank(points)
    assert rank["a"] < rank["c"] < rank["b"] < rank["d"]  # 同层难度低者先


def test_topological_same_layer_prefers_high_weight():
    points = [kp("low", weight=5), kp("high", weight=30)]
    rank = study_scheduler.topological_rank(points)
    assert rank["high"] < rank["low"]


# ---------- schedule_tasks ----------

def test_schedule_packs_by_daily_budget():
    points = [kp("a"), kp("b"), kp("c")]
    tasks = [
        task("t1", "a", duration=60),
        task("t2", "b", duration=60),
        task("t3", "c", duration=90),
    ]
    warnings = study_scheduler.schedule_tasks(tasks, points, session_days=[1, 2], daily_minutes=120)
    assert warnings == []
    by_day = {}
    for t in tasks:
        by_day.setdefault(t["day"], []).append(t["duration"])
    assert sum(by_day.get(1, [])) <= 120
    assert sum(by_day.get(2, [])) <= 120
    assert sorted(t["order"] for t in tasks) == [1, 2, 3]


def test_schedule_uses_sparse_review_days():
    points = [kp(f"p{i}") for i in range(4)]
    tasks = [task(f"t{i}", f"p{i}", duration=60) for i in range(4)]
    study_scheduler.schedule_tasks(tasks, points, session_days=[1, 4, 7], daily_minutes=120)
    assert all(t["day"] in {1, 4, 7} for t in tasks)


def test_schedule_respects_prerequisite_order():
    points = [
        kp("basic", difficulty=1),
        kp("advanced", difficulty=4, prereqs=["basic"]),
    ]
    tasks = [task("t-adv", "advanced"), task("t-basic", "basic")]
    study_scheduler.schedule_tasks(tasks, points, session_days=[1, 2], daily_minutes=120)
    basic = next(t for t in tasks if t["knowledgePointId"] == "basic")
    advanced = next(t for t in tasks if t["knowledgePointId"] == "advanced")
    assert (basic["day"], basic["order"]) < (advanced["day"], advanced["order"])
    assert "需先完成" in advanced["schedulingReason"]
    assert "basic" in advanced["schedulingReason"]


def test_schedule_overflow_goes_to_last_day_with_warning():
    points = [kp("a"), kp("b")]
    tasks = [task("t1", "a", duration=120), task("t2", "b", duration=120)]
    warnings = study_scheduler.schedule_tasks(tasks, points, session_days=[1], daily_minutes=120)
    assert any("超出每日复习时长" in w for w in warnings)
    assert all(t["day"] == 1 for t in tasks)


# ---------- reprioritize_pending ----------

def test_reprioritize_empty_graph_preserves_existing_mainline_order():
    """空图降级：失分/掌握度不再插队，只保持已生成的 day/order 主线。"""
    points = [
        kp("weak", mastery=20, weight=30),
        kp("strong", mastery=90, weight=10),
        kp("mid", mastery=55, weight=20),
    ]
    tasks = [
        task("t1", "strong", day=1, order=1),
        task("t2", "weak", day=1, order=2, priority="high"),
        task("t3", "mid", day=2, order=3),
    ]
    expected_ids = ["t1", "t2", "t3"]
    study_scheduler.reprioritize_pending(tasks, points, session_days=[1, 2], daily_minutes=120)
    assert [t["id"] for t in tasks] == expected_ids
    assert [t["order"] for t in tasks] == [1, 2, 3]


def test_reprioritize_failed_kp_cannot_jump_pending_prerequisite():
    points = [
        kp("basic"),
        kp("adv", prereqs=["basic"]),
    ]
    tasks = [
        task("t-basic", "basic", day=1, order=1),
        task("t-adv", "adv", day=2, order=2, priority="high"),
    ]
    warnings = study_scheduler.reprioritize_pending(tasks, points, session_days=[1, 2], daily_minutes=120)
    adv = next(t for t in tasks if t["knowledgePointId"] == "adv")
    basic = next(t for t in tasks if t["knowledgePointId"] == "basic")
    # 失分高优知识点也绝不能排到未完成前置之前。
    assert (adv["day"], adv["order"]) > (basic["day"], basic["order"])


def test_reprioritize_does_not_insert_failed_kp_after_prerequisite_completed():
    points = [
        kp("basic"),
        kp("adv", prereqs=["basic"]),
    ]
    tasks = [
        task("t-basic", "basic", day=1, order=1, status="completed"),
        task("t-far", "other", day=2, order=2),
        task("t-adv", "adv", day=3, order=3, priority="high"),
    ]
    points.append(kp("other"))
    study_scheduler.reprioritize_pending(tasks, points, session_days=[1, 2, 3], daily_minutes=120)
    adv = next(t for t in tasks if t["knowledgePointId"] == "adv")
    far = next(t for t in tasks if t["knowledgePointId"] == "other")
    # 前置已完成也不允许高优/失分知识点越过同层主线知识点；失分只加时长/题量。
    assert (far["day"], far["order"]) < (adv["day"], adv["order"])


def test_reprioritize_frozen_tasks_keep_position():
    points = [kp("a"), kp("b", prereqs=["a"])]
    tasks = [
        task("t-a-done", "a", day=3, order=5, status="completed"),
        task("t-a-now", "a", day=1, order=1, status="in-progress"),
        task("t-b", "b", day=2, order=2),
    ]
    study_scheduler.reprioritize_pending(tasks, points, session_days=[1, 2, 3], daily_minutes=180)
    frozen = next(t for t in tasks if t["id"] == "t-a-done")
    inprog = next(t for t in tasks if t["id"] == "t-a-now")
    # 冻结任务的 day 不动；order 全局重编后会变，但其"当日首位"的相对位置保持。
    assert frozen["day"] == 3
    assert inprog["day"] == 1
    # 全局 order 重编连续。
    assert sorted(t["order"] for t in tasks) == [1, 2, 3]


# ---------- find_dag_violations / enforce_dag_order ----------

def test_find_violations_detects_manual_override():
    points = [kp("basic"), kp("adv", prereqs=["basic"])]
    tasks = [
        task("t-adv", "adv", day=1, order=1),   # 被手动拉到前面
        task("t-basic", "basic", day=2, order=2),
    ]
    violations = study_scheduler.find_dag_violations(tasks, points)
    assert len(violations) == 1
    assert violations[0]["taskId"] == "t-adv"
    assert violations[0]["prerequisiteNames"] == ["basic"]


def test_enforce_dag_order_defers_violating_task():
    points = [kp("basic"), kp("adv", prereqs=["basic"])]
    tasks = [
        task("t-adv", "adv", day=1, order=1),
        task("t-basic", "basic", day=2, order=2),
    ]
    fixed, warnings = study_scheduler.enforce_dag_order(
        tasks, points, session_days=[1, 2, 3], daily_minutes=120
    )
    adv = next(t for t in fixed if t["id"] == "t-adv")
    basic = next(t for t in fixed if t["id"] == "t-basic")
    assert (adv["day"], adv["order"]) > (basic["day"], basic["order"])
    assert any("顺延" in w for w in warnings)


def test_enforce_dag_noop_without_violations():
    points = [kp("a"), kp("b", prereqs=["a"])]
    tasks = [task("t-a", "a", day=1), task("t-b", "b", day=2)]
    snapshot = copy.deepcopy(tasks)
    fixed, warnings = study_scheduler.enforce_dag_order(
        tasks, points, session_days=[1, 2], daily_minutes=120
    )
    assert warnings == []
    assert fixed == snapshot


# ---------- 集成：apply_operations_to_copy 硬校验 ----------

def test_apply_operations_rejects_dag_violation():
    from app.agents.tools import apply_operations_to_copy

    workspace = {
        "knowledgePoints": [kp("basic"), kp("adv", prereqs=["basic"])],
        "tasks": [
            task("t-basic", "basic", day=2, order=2),
            task("t-adv", "adv", day=3, order=3),
        ],
    }
    # AI 提案把前置 basic 推迟到 adv 之后（day 4）→ 依赖任务在前面，应硬失败。
    operations = [{"type": "move_task", "task_id": "t-basic", "day": 4, "order": 1}]
    try:
        apply_operations_to_copy(workspace, operations)
        raise AssertionError("应当抛出 ValueError")
    except ValueError as error:
        assert "前置依赖" in str(error)


def test_apply_operations_tolerates_baseline_violation():
    """存量违规不毒化后续提案：基线里 adv 本就排在 basic 前，合法移动应放行。"""
    from app.agents.tools import apply_operations_to_copy

    workspace = {
        "knowledgePoints": [kp("basic"), kp("adv", prereqs=["basic"])],
        "tasks": [
            task("t-adv", "adv", day=1, order=1),    # 存量违规
            task("t-basic", "basic", day=2, order=2),
            task("t-other", "", day=2, order=3),
        ],
    }
    # 移动无依赖任务不产生新违规 → 应成功（旧逻辑会因存量违规全量否决）。
    result = apply_operations_to_copy(
        workspace, [{"type": "move_task", "task_id": "t-other", "day": 3, "order": 1}]
    )
    other = next(t for t in result if t["id"] == "t-other")
    assert other["day"] == 3


def test_apply_operations_still_rejects_worsening_move():
    """基线违规存在时，把事情变更糟（新增违规对）仍要拒绝。"""
    from app.agents.tools import apply_operations_to_copy

    workspace = {
        "knowledgePoints": [
            kp("basic"),
            kp("adv", prereqs=["basic"]),
            kp("adv2", prereqs=["basic"]),
        ],
        "tasks": [
            task("t-adv", "adv", day=1, order=1),    # 存量违规：adv 在 basic 前
            task("t-basic", "basic", day=2, order=2),
            task("t-adv2", "adv2", day=2, order=3),  # 本无违规：在 basic 之后
        ],
    }
    # 把 basic 挪到 adv2 之后 → 给 adv2 新造一个违规（存量 t-adv 的违规不变）。
    operations = [{"type": "move_task", "task_id": "t-basic", "day": 3, "order": 1}]
    try:
        apply_operations_to_copy(workspace, operations)
        raise AssertionError("应当抛出 ValueError")
    except ValueError as error:
        assert "前置依赖" in str(error)


# ---------- restructure_modules：模块重组提案 ----------

def _restructure_operation():
    return {
        "type": "restructure_modules",
        "modules": [
            {
                "id": "m-mem",
                "title": "内存管理",
                "pointIds": ["virtual", "paging"],
            },
            {
                "id": "m-proc",
                "title": "进程管理",
                "pointIds": ["syscall", "process"],
            },
        ],
        "prerequisitesOverride": {"virtual": []},
    }


def _restructure_workspace():
    # 主线换轴前的布局：进程模块在前（process 依赖 syscall），内存的 virtual 依赖 process。
    return {
        "modules": [
            {"id": "m-proc", "title": "进程", "order": 1},
            {"id": "m-mem", "title": "内存", "order": 2},
        ],
        "knowledgePoints": [
            kp("syscall", "系统调用", module="m-proc"),
            kp("process", "进程线程", prereqs=["syscall"], module="m-proc"),
            kp("virtual", "虚拟地址", prereqs=["process"], module="m-mem"),
            kp("paging", "分页", prereqs=["virtual"], module="m-mem"),
        ],
        "tasks": [
            task("t-syscall", "syscall", day=1, order=1),
            task("t-process", "process", day=1, order=2),
            task("t-virtual", "virtual", day=2, order=3),
            task("t-paging", "paging", day=2, order=4),
        ],
    }


def test_restructure_modules_swaps_mainline():
    """内存主线提前：内存块整体排在进程块前，且依赖 override 后无回边。"""
    from app.agents.tools import apply_operations_to_copy, build_module_reconcile

    workspace = _restructure_workspace()
    result = apply_operations_to_copy(
        workspace,
        [_restructure_operation()],
        reconcile=build_module_reconcile([1, 2], 240),
    )
    assert isinstance(result, dict) and "modules" in result
    kp_order = {t["id"]: t["order"] for t in result["tasks"]}
    # 内存块（virtual/paging）整体先于进程块（syscall/process）。
    assert max(kp_order["t-virtual"], kp_order["t-paging"]) < min(
        kp_order["t-syscall"], kp_order["t-process"]
    )
    # override 生效：virtual 不再依赖 process。
    virtual = next(p for p in result["knowledgePoints"] if p["id"] == "virtual")
    assert virtual["prerequisites"] == []
    assert virtual["moduleId"] == "m-mem"
    # 重排后无违规。
    assert study_scheduler.find_dag_violations(result["tasks"], result["knowledgePoints"]) == []


def test_restructure_modules_rejects_incomplete_coverage():
    from app.agents.tools import apply_operations_to_copy, build_module_reconcile

    workspace = _restructure_workspace()
    operation = _restructure_operation()
    operation["modules"] = operation["modules"][:1]  # 漏掉进程模块的知识点
    try:
        apply_operations_to_copy(
            workspace, [operation], reconcile=build_module_reconcile([1, 2], 240)
        )
        raise AssertionError("应当抛出 ValueError")
    except ValueError as error:
        assert "覆盖全部知识点" in str(error)


def test_restructure_modules_must_be_solo():
    from app.agents.tools import apply_operations_to_copy, build_module_reconcile

    workspace = _restructure_workspace()
    operations = [
        _restructure_operation(),
        {"type": "change_priority", "task_id": "t-paging", "priority": "high"},
    ]
    try:
        apply_operations_to_copy(
            workspace, operations, reconcile=build_module_reconcile([1, 2], 240)
        )
        raise AssertionError("应当抛出 ValueError")
    except ValueError as error:
        assert "单独成案" in str(error)


def test_restructure_modules_rejects_unknown_prereq_override():
    from app.agents.tools import apply_operations_to_copy, build_module_reconcile

    workspace = _restructure_workspace()
    operation = _restructure_operation()
    operation["prerequisitesOverride"] = {"paging": ["ghost-id"]}
    try:
        apply_operations_to_copy(
            workspace, [operation], reconcile=build_module_reconcile([1, 2], 240)
        )
        raise AssertionError("应当抛出 ValueError")
    except ValueError as error:
        assert "未知前置" in str(error)


# ---------- topological_rank 模块主线模式 ----------

def test_topological_module_mainline_blocks_by_module_order():
    """依赖兼容时按模块 order 分块：内存模块(1)整块先于进程模块(2)。"""
    points = [
        kp("virtual", "虚拟地址", module="m-mem"),
        kp("paging", "分页", prereqs=["virtual"], module="m-mem"),
        kp("syscall", "系统调用", module="m-proc"),
        kp("process", "进程", prereqs=["syscall"], module="m-proc"),
    ]
    modules = [
        {"id": "m-mem", "title": "内存", "order": 1},
        {"id": "m-proc", "title": "进程", "order": 2},
    ]
    rank = study_scheduler.topological_rank(points, modules)
    assert max(rank["virtual"], rank["paging"]) < min(rank["syscall"], rank["process"])


def test_topological_falls_back_to_layering_on_back_edge():
    """存在跨模块回边（进程→内存的依赖）时退回全局分层，不按模块分块。"""
    points = [
        kp("virtual", "虚拟地址", module="m-mem"),
        # paging 依赖 process（模块2）→ 内存块内出现回边，主线模式不可用。
        kp("paging", "分页", prereqs=["process"], module="m-mem"),
        kp("syscall", "系统调用", module="m-proc"),
        kp("process", "进程", prereqs=["syscall"], module="m-proc"),
    ]
    modules = [
        {"id": "m-mem", "title": "内存", "order": 1},
        {"id": "m-proc", "title": "进程", "order": 2},
    ]
    rank = study_scheduler.topological_rank(points, modules)
    # 全局分层下 paging（层3）必然晚于 process（层2），但内存块不再整块在前。
    assert rank["process"] < rank["paging"]


# ---------- 集成：_sanitize_custom_workspace 走调度器 ----------

def test_sanitize_custom_workspace_schedules_by_dag():
    from app import study_service

    candidate = {
        "modules": [{"id": "m-1", "title": "模块一", "order": 1}],
        "knowledgePoints": [
            kp("basic", "基础知识", difficulty=1, mastery=30),
            kp("adv", "进阶应用", difficulty=4, prereqs=["basic"], mastery=30),
        ],
        "tasks": [
            task("t-adv", "adv", day=1, order=1, duration=60),
            task("t-basic", "basic", day=1, order=2, duration=60),
        ],
        "practiceQuestions": [],
        "mockQuestions": [],
    }
    base = {
        "course": {"id": "test-course"},
        "onboarding": {"days": 4, "reviewCount": 2, "dailyHours": 2},
    }
    workspace = study_service._sanitize_custom_workspace(candidate, base, materials=[])
    adv = next(t for t in workspace["tasks"] if t["knowledgePointId"] == "adv")
    basic = next(t for t in workspace["tasks"] if t["knowledgePointId"] == "basic")
    assert (basic["day"], basic["order"]) < (adv["day"], adv["order"])
    assert "需先完成【基础知识】" in adv["schedulingReason"]
    assert "schedulingWarnings" in workspace


def test_sanitize_custom_workspace_empty_graph_keeps_legacy_remap():
    """无依赖 candidate 走旧 _remap 路径（空图降级），行为不变。"""
    from app import study_service

    candidate = {
        "modules": [{"id": "m-1", "title": "模块一", "order": 1}],
        "knowledgePoints": [kp("a"), kp("b")],
        "tasks": [
            task("t1", "a", day=1, order=1),
            task("t2", "b", day=3, order=2),
        ],
        "practiceQuestions": [],
        "mockQuestions": [],
    }
    base = {
        "course": {"id": "test-course"},
        "onboarding": {"days": 4, "reviewCount": 2, "dailyHours": 2},
    }
    workspace = study_service._sanitize_custom_workspace(candidate, base, materials=[])
    days = sorted({t["day"] for t in workspace["tasks"]})
    # reviewCount=2, days=4 → 复习日 [1, 4]（_review_session_days: j=1 → 1+3=4）。
    assert days == [1, 4]


# ---------- 第0天·复习导引（orientation）豁免逻辑 ----------

def test_orientation_pinned_and_budget_free_in_schedule():
    orient, _ = orientation_task()
    points = [kp("a"), kp("b")]
    tasks = [
        orient,
        task("t1", "a", duration=60),
        task("t2", "b", duration=70),
    ]
    # 若导引的 15 分钟计入预算，t1+t2+导引 = 145 > 120，t2 会被挤到第 2 天。
    study_scheduler.schedule_tasks(tasks, points, session_days=[1], daily_minutes=120)
    assert (orient["day"], orient["order"]) == (0, 0)
    assert tasks[0] is orient
    assert all(t["day"] == 1 for t in tasks if t is not orient)


def test_orientation_survives_legacy_sort_and_reprioritize():
    orient, _ = orientation_task()
    points = [kp("a"), kp("b")]
    tasks = [
        task("t1", "a", day=1, order=1),
        orient,
        task("t2", "b", day=2, order=2),
    ]
    study_scheduler.reprioritize_pending(tasks, points, session_days=[1, 2], daily_minutes=120)
    # 无 knowledgePointId 的导引不能被推进"最后一天兜底桶"，必须保持置顶。
    assert tasks[0] is orient
    assert (orient["day"], orient["order"]) == (0, 0)
    assert sorted(t["order"] for t in tasks if t is not orient) == [1, 2]


def test_orientation_survives_enforce_dag_order():
    orient, _ = orientation_task()
    points = [kp("basic"), kp("adv", prereqs=["basic"])]
    tasks = [
        orient,
        task("t-adv", "adv", day=1, order=1),
        task("t-basic", "basic", day=2, order=2),
    ]
    fixed, warnings = study_scheduler.enforce_dag_order(
        tasks, points, session_days=[1, 2, 3], daily_minutes=120
    )
    first = fixed[0]
    # 重编 order 时导引不能被编成 1 号，保持 day=0/order=0 置顶。
    assert first is orient
    assert (first["day"], first["order"]) == (0, 0)
    rest_orders = sorted(t["order"] for t in fixed if t is not orient)
    assert rest_orders == [1, 2]


def test_orientation_excluded_from_overdue():
    from datetime import date, timedelta

    from app import study_service

    orient, _ = orientation_task()
    base = {
        "course": {"id": "test-course"},
        "planStartDate": (date.today() - timedelta(days=2)).isoformat(),
        "tasks": [
            orient,
            task("t-old", "a", day=1, order=1),
            task("t-far", "b", day=3, order=1),
        ],
    }
    progress = study_service.build_daily_progress(base)
    assert progress["todayDay"] == 3
    # day=0 < todayDay 恒成立，但导引绝不进逾期列表。
    assert all(item["id"] != orient["id"] for item in progress["overdue"])
    assert any(item["id"] == "t-old" for item in progress["overdue"])


def test_orientation_skipped_by_content_quality_guard():
    from app import study_service

    orient, _ = orientation_task()
    orient["contentQualityWarning"] = "遗留警告"
    workspace = {
        "course": {"id": "test-course", "name": "测试课"},
        "onboarding": {"status": "planned", "days": 4, "dailyHours": 2},
        "knowledgePoints": [kp("a")],
        "tasks": [orient, task("t1", "a", day=1, order=1)],
        "materials": [],
    }
    study_service._ensure_workspace_content_quality(workspace)
    # 导引无 examPoints/objectives 顶层字段，必须被跳过：清掉遗留警告且不注入 4 段式 sections。
    assert "contentQualityWarning" not in orient
    assert "sections" not in (orient.get("studyGuide") or {})


def test_apply_operations_rejects_orientation_move():
    from app.agents.tools import apply_operations_to_copy

    orient, orient_id = orientation_task()
    workspace = {
        "knowledgePoints": [kp("a")],
        "tasks": [orient, task("t1", "a", day=1, order=1)],
    }
    operations = [{"type": "move_task", "task_id": orient_id, "day": 3, "order": 1}]
    try:
        apply_operations_to_copy(workspace, operations)
        raise AssertionError("应当抛出 ValueError")
    except ValueError as error:
        assert "导引" in str(error)


def test_backup_orientation_guide_zero_issues():
    from app.agents.workflow import _backup_orientation_guide, _orientation_guide_issues

    course = {"id": "test-course", "name": "测试课", "examDate": "2099-01-01", "targetScore": 90}
    onboarding = {"days": 6, "dailyHours": 2}
    modules = [{"id": "m-1", "title": "模块一", "order": 1}]
    points = [kp("a", "基础"), kp("b", "进阶", prereqs=["a"])]
    tasks = [task(f"t{i}", pid, day=i, order=1) for i, pid in enumerate(["a", "b"], start=1)]
    guide = _backup_orientation_guide(
        course=course,
        onboarding=onboarding,
        modules=modules,
        knowledge_points=points,
        tasks=tasks,
    )
    # 兜底模板必须零 issue 通过自身校验（LLM 失败时功能仍可用）。
    assert _orientation_guide_issues(guide, expected_days=6) == []

def test_schedule_preserves_27_lesson_planner_mainline_across_study_metrics():
    modules = [
        {"id": "process", "title": "进程管理", "order": 1},
        {"id": "memory", "title": "内存管理", "order": 2},
        {"id": "files", "title": "文件系统", "order": 3},
    ]
    points = []
    tasks = []
    for index in range(27):
        module_id = modules[index // 9]["id"]
        point_id = f"p-{index + 1}"
        points.append({
            "id": point_id,
            "name": point_id,
            "moduleId": module_id,
            "difficulty": 5 - (index % 5),
            "weight": 30 - index,
            "mastery": (index * 17) % 100,
            "prerequisites": [f"p-{index}"] if index % 9 and index % 3 == 0 else [],
        })
        tasks.append(task(f"t-{index + 1}", point_id, day=index // 3 + 1, order=index + 1, duration=30))

    expected_ids = [item["id"] for item in tasks]
    study_scheduler.schedule_tasks(tasks, points, session_days=list(range(1, 10)), daily_minutes=90, modules=modules)

    assert [item["id"] for item in tasks] == expected_ids
    assert [item["order"] for item in tasks] == list(range(1, 28))
    assert [item["day"] for item in tasks] == [day for day in range(1, 10) for _ in range(3)]
