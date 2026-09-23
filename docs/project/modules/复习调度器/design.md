# 复习调度器（scheduler）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

知识点前置依赖 DAG 的唯一调度权威：依赖消毒/断环、拓扑排序、任务装包到复习日、重排/再平衡。全部纯函数、无 IO、仅标准库，操作 workspace.json 内的 dict。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 纯函数无 IO | 可测性（716 行测试）；所有调用方（review_plan/tools/orientation/practice）共享同一口径 |
| Planner 主线权威：tasks 原序不可被 difficulty/weight/mastery 重排 | `_stable_mainline_tasks`（L450 注释：旧实现已废弃）；失分只加强度不插队 |
| 断环删"target weight 最低，tie id 字典序"边 | 确定性断环，迭代至无环 + 防御上限 |
| FROZEN_STATUSES=("completed","in-progress") 冻结 (day,order) | 已学内容不被重排打乱 |
| 装不下→末日 + 显式 schedulingWarning | 不静默吞掉超载 |
| 提案 DAG 校验"只拒绝相对基线新增违规" | 允许存量违规暂存，阻止恶化 |

## 不变量

- orientation 任务恒 (day=0, order=0) 置顶
- `_review_session_days` 用 `int(raw+0.5)` 对齐 JS Math.round——**改后端必须同步前端 reviewSchedule.ts**（银行家舍入差异教训）
- 空图降级 `_legacy_sort` 保持已生成主线
- PREREQUISITE_EDGE_LABEL="前置"、KP_MASTERY_DONE_THRESHOLD=60

## 禁区

- 不在此域引入 IO/时间获取（纯函数契约）
- 不许绕过 `enforce_dag_order` 直接改 tasks 的 day/order（手动调整必须过校验）

## 设计异议

（无）
