# 规划（planning）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| backend/app/strategy.py | 478 | 文档读写/版本化/初稿生成/审阅保存/维护标记/草稿修订 revise_strategy_draft |
| backend/app/agents/strategy_workflow.py | 228 | 三 Agent 顺序生成画像→计划→Prompt 并渲染 Markdown |
| backend/app/routers/strategy.py | 277 | 策略 HTTP 端点 + 提案采纳 |
| web/src/components/PlanningView.tsx | 438 | 跨课程月度日历视图 |
| web/src/hooks/useStrategyGenerationJob.ts | 162 | approve 生成任务轮询 |
| web/src/components/ModuleView.tsx | — | StrategyReviewView(L1613)/StrategySection(L1920) 审阅 UI |

## 调用链

routers/strategy.py → study_service 门面（L1161 re-export；strategy.py 函数体内延迟 import 跨域符号——缝合点）。生成：`generate_strategy_documents`(L210) → sync_course_knowledge + retrieve_material_context → `run_strategy_workflow`(L78)。审阅：`save_strategy_documents`(L272，乐观版本锁)。修订：POST …/revise → `revise_strategy_draft`(L353，SSE，`_stream_model_turn`)。前端经 App.tsx handlers 以 props 下传 ModuleView。

## 数据契约

- 无 DB 表；workspace.json `strategyDocuments`：{status('generating'\|'review'\|'approved'\|'maintenance-error'), reviewPlan/coursePrompt 元数据{path,version,updatedAt,updatedBy,changeSummary}, maintenancePending, maintenanceError, lastAgentRunId, reviewReport}
- 文件：data/courses/<id>/strategy/ 下 review-plan.md、course-prompt.md + history/-vNNNN.md
- 端点：GET/PUT strategy-documents、/generate、/approve、/approve-job(202)、GET active-job、PUT course-prompt、POST revise(SSE)、POST adjustment-proposals/{pid}/apply\|dismiss
- TS：types.ts L620-634 StrategyDocument/StrategyDocuments

## 测试锚点

test_strategy_revision.py（4 测试：ok_and_no_write/history_roundtrip/bad_output_emits_error/rejects_empty_input_draft，打桩 `study_service._stream_model_turn`）；调用方覆盖：test_mainline_generation_repair、test_answer_consistency、test_facade_exports、test_workflow_modularization

## 上游调用方 / 下游消费方

- 依赖：模型调用、RAG检索、后台队列（approve=0 最高优先级）、存储与工作区（_strategy_directory/_atomic_write_text）
- 下游：课程生成流水线（approve_strategy_documents 入口）、复习计划（review-plan.md 由本域读写）

## 导读

读序：strategy.py（文档生命周期）→ strategy_workflow.py（三 Agent 编排）→ routers/strategy.py。改修订流程先看 test_strategy_revision 的定界标记契约。
