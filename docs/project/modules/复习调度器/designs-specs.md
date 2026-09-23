# 复习调度器（scheduler）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| backend/app/study_scheduler.py | 832 | 全部纯函数：sanitize_dependencies/_find_cycle/topological_rank/schedule_tasks/reprioritize_pending/find_dag_violations/enforce_dag_order/split_orientation 等 |
| backend/app/review_plan.py | 545 | 调度结果消费者：maintain_review_plan（AI 维护，版本比对防覆盖）、build_daily_progress、record_time/delete_time_entry（幂等）、rebalance_daily_plan、replan_review_mainline、update_workspace_state（L529 过 enforce_dag_order） |
| backend/app/study_service.py | — | _review_session_days(L115)/_remap_tasks_to_review_sessions(L142)/_sanitize_custom_workspace(L577 调度接管) |
| backend/app/agents/tools.py | 1019 | apply_operations_to_copy(L426)/_reject_new_dag_violations/build_module_reconcile |
| backend/app/practice.py | — | _prioritize_tasks(L380) 调 reprioritize_pending |

## 调用链（四个入口）

生成：POST /strategy-documents/approve-job → content_workflow → `_sanitize_custom_workspace` → `sanitize_dependencies` + `schedule_tasks`。失分：POST /practice/answer → `reprioritize_pending`。手动调整：PUT /workspace → `update_workspace_state` → `enforce_dag_order`。提案 apply：→ `apply_operations_to_copy` → `find_dag_violations` 硬校验。展示：GET /workspace → `build_daily_progress`。

## 数据契约

无自有表；操作 workspace.json：tasks[]（id/knowledgePointId/day/order/duration/status/priority/kind/schedulingReason）、knowledgePoints[]（prerequisites/difficulty/weight/mastery/moduleId）、workspace.schedulingWarnings、planStartDate、timeLog[]、onboarding.days/reviewCount/dailyHours。

## 测试锚点

test_study_scheduler.py（716 行 ~30 用例：apply_operations 硬校验/restructure_modules/orientation 豁免/27 课主线保持）、test_time_log_idempotency.py、test_facade_exports.py（review_plan 门面）

## 上游调用方 / 下游消费方

- 域内最底层：仅标准库零依赖；被 workspace/agents/orientation/review_plan/study_service/practice 六方 import

## 导读

读序：schedule_tasks（装包主口径）→ _stable_mainline_tasks（主线权威）→ reprioritize_pending（失分重排）。改舍入/排序逻辑前先读 test_study_scheduler.py 对应用例与前端 reviewSchedule.ts 的对齐注释。
