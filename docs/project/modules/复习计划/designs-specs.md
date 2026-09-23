# 复习计划（review-plan）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| backend/app/review_plan.py | 545 | AI 维护/每日进度/时长记录/顺延减负提案/重排提案/手动更新 |
| backend/app/routers/courses.py | 787 | workspace/plan/adjust 端点 |
| backend/app/routers/practice.py | 206 | time-log 端点 |
| backend/app/main.py | — | L44-114 job worker 注册（_maintain_plan_job/_rebalance_plan_job） |
| web/src/components/ModuleView.tsx | — | PlanView(L996)/RebalanceProposalCard(L559)/AdjustTodayPlanDialog(L628)/AdjustPlanParamsDialog(L843) |
| web/src/utils/reviewSchedule.ts | 32 | 复习日分布前端镜像（必须与后端同步） |

## 调用链

`maintain_review_plan`(L31) 经 agent_jobs 异步（9 处事件入队）；GET /workspace → `build_daily_progress` + `list_pending_proposals`，超额自动入队 `rebalance_daily_plan`(L257，冷却 30min)；POST /plan/adjust(L444) 分轻量/重排两路；PUT /workspace(L523) → `update_workspace_state` → `enforce_dag_order` + `record_review_progress`（review_sections 表）；POST\|DELETE /time-log → `record_time`/`delete_time_entry`（幂等 client_entry_id）。提案采纳：`apply_proposal`(agents/tools.py:949) → `apply_operations_to_copy`(L426)。前端 App.tsx handlers L1200-1316，updateWorkspaceTasks(L855) 乐观更新+对账。

## 数据契约

- workspace.json：tasks[]、timeLog[]{id,taskId,date,minutes,note,createdAt}、planStartDate、planRevision、schedulingWarnings、onboarding{days,reviewCount,dailyHours,examDate}
- dailyProgress（types.ts:897）：{date,todayDay,maxDay,plannedToday,spentToday,remaining,overBudget,overdue[]}
- SQLite：adjustment_proposals 表（base_revision/operations_json/before/after/params_json）、agent_jobs、review_sections
- 端点：GET/PUT workspace、POST /plan/adjust、POST/DELETE /time-log[/{entry_id}]、GET /plan

## 测试锚点

test_study_scheduler.py（715 行 40 测试：预算打包/reprioritize 冻结/enforce_dag_order 顺延/apply_operations 基线对比/restructure_modules/导引钉住/27 课主线保持）、test_time_log_idempotency.py（4 测试）

## 上游调用方 / 下游消费方

- 依赖：规划（review-plan.md 文档读写与 coursePrompt 上下文）、后台队列（maintain=4/rebalance=5 最低优先级）、模型调用、存储与工作区、复习调度器、RAG检索（record_review_progress）
- 前端 demo 镜像 demoApi.ts:226 也重算 dailyProgress

## 导读

读序：review_plan.py 自上而下 → study_scheduler 的对应纯函数 → PlanView（L996 起）。改日历/进度展示先对齐 reviewSchedule.ts 与 _review_session_days 的舍入约定。
