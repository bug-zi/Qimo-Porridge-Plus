# 课程生成流水线（content-pipeline）｜designs-specs.md

> AI 生成并维护（2026-09-24 基于代码逆向生成）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件（backend/app/agents/ 除注明外） | 行数 | 职责 |
|---|---|---|
| content_workflow.py | 506 | 主编排 `run_content_workflow`：规划→逐节→模拟卷→导引→落盘 |
| lesson_generation.py | 365 | `LessonBuilder.build` 单节三段：讲义初稿→patch→自测→patch→合并 checkpoint |
| question_generation.py | 438 | 模拟题校验 `_question_issues`/`_mock_blueprint_issues`、兜底 `_backup_mock_questions`、独立修复 `repair_mock_questions` |
| content_validation.py | 372 | 硬校验 `_study_guide_issues`/`_deterministic_review`/`_plan_issues`、软硬伤拆分 `split_guide_issues` |
| content_patches.py | 160 | patch 路径解析 `_segments` 与合并 `apply_guide_patches`/`apply_question_patches` |
| content_prompts.py | 76 | CONTENT_PLANNER / LESSON_CONTENT(_PATCH) / LESSON_PRACTICE(_PATCH) / MOCK_EXAM_PROMPT |
| checkpoint_contracts.py | 108 | 签名与契约版本常量 |
| answer_consistency.py | 48 | `reconcile_question_answer` 解析结论一致性 |
| formula_rules.py | 18 | `with_structured_formula_rules` KaTeX 输出约束 |
| readability_review.py | 193 | `review_study_guide` / `build_course_readability_review` |
| lesson_fallbacks.py | 152 | 旧降级模板，仅门面导出，主线不调用 |
| orientation.py | 264 | 第0天导引 `build_orientation_guide`（task-day0-orientation） |
| contracts.py / workflow.py / workflow_types.py | 107/65/5 | ReviewReport 模型 / 兼容门面 / 类型别名 |
| ../course_style_templates.py | 147 | standard(v1)/dialogue(v1)/story(v6) 三风格模板 |

## 调用链

main.py 注册 `_approve_strategy_documents_job` → AgentJobWorker（后台队列域：lease 心跳+硬超时）→ `approve_strategy_documents`（study_service ≈L937，版本校验→`sync_course_knowledge`→RAG 证据）→ `run_content_workflow`（content_workflow.py:43）：
① 内容规划（签名命中缓存/模型/一次修复，失败 raise）→ 存 content_plan_checkpoint
② 逐 task `LessonBuilder.build`：`generate_guide`→硬伤→`patch_guide`→仍硬伤 raise；`generate_questions`→硬伤→`apply_question_patches`→仍硬伤 raise → 存 lesson_content_checkpoint；每节 on_progress("lesson_built") → `_write_content_lesson_preview`（study_service:733）增量写 workspace
③ content_complete 后 `build_mock_questions` ④ 注入 orientation（kind 判重幂等） ⑤ `build_course_readability_review` ⑥ save_artifact（review_report + content_bundle），终局 repair/continue 走 `_merge_repaired_content`（630），否则 `_sanitize_custom_workspace`。前端经 useStrategyGenerationJob 轮询。

## 数据契约

- **artifact**（artifacts 表：type/version/status/content_json/source_run_id）：`content_plan_checkpoint{signature,candidate}`、`lesson_guide_checkpoint:{tid}`、`lesson_questions_checkpoint:{tid}`、`lesson_content_checkpoint:{tid}`、`lesson_guide_failed:{tid}`（失败原稿）、`lesson_guide_patch/lesson_questions_patch:{tid}`（inputReviewIssues/patchOutput/remainingIssues）、`mock_questions_checkpoint`、`review_report`、`content_bundle`；status ∈ checkpoint/failed/approved/partial
- **签名与版本**：`stable_signature`=sha256+排序 JSON；FORMULA_OUTPUT_CONTRACT_VERSION=1、LESSON_CONTENT_CONTRACT_VERSION=4、QUESTION_CHECKPOINT_VERSION=1、MOCK_BLUEPRINT_PROMPT_VERSION=2、GUIDE_SIGNATURE_PREFIX="split-guide-v2:"；风格模板 version（story=6）进 `lesson_content_signature`，升版即旧 checkpoint 全量失效
- **patch**：点号+下标 `sections[1].explanationBeats[2].body`，JSON Pointer `/sections/0` 归一化等价；深度≤8；guide 根白名单 {examPoints,workedExamples,storyContext,sections}；题字段白名单；禁改 id/taskId/knowledgePointId/source；op=replace/add/remove(+add_question)；patches≤12
- **workspace 写入**：tasks[].studyGuide/contentQualityWarning、practiceQuestions、mockQuestions、readabilityReview、strategyDocuments.reviewReport、generationWarning、onboarding.status、workspaceContentVersion

## 测试锚点

test_content_patches、test_checkpoint_contracts、test_lesson_question_draft、test_mainline_generation_repair、test_story_lesson_contract、test_course_style_templates、test_strong_feedback_generation、test_mock_questions_repair、test_answer_consistency、test_readability_review、test_workflow_modularization、test_facade_exports、test_agent_job_queue、test_course_feedback_replacement（均在 backend/tests/）

## 上游调用方 / 下游消费方

- 上游：后台队列（job 触发）、规划域（策略文档版本）、RAG检索（retrieve_material_context 证据）、课程意见反馈（MUST- 强反馈规则注入 course_prompt）
- 下游：复习主线（workspace 的 studyGuide/practiceQuestions/mockQuestions 渲染）、总览（readabilityReview）、知识地图（mind_map 归并依赖内容齐备）

## 导读

新人读序：content_workflow.py（骨架）→ lesson_generation.py（单节最复杂）→ content_validation.py（硬校验口径）→ content_patches.py（patch 语义）→ checkpoint_contracts.py（缓存失效机制）。改提示词先看 content_prompts.py 与 course_style_templates.py 的 version 联动。
