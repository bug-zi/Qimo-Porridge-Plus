# 存储与工作区（storage）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| backend/app/paths.py | 23 | 路径常量唯一定义点（DATA_DIRECTORY/COURSES_DATA_DIRECTORY/DATABASE_PATH/MODEL_PROFILES_PATH 等），零依赖 |
| backend/app/workspace.py | 466 | load/save/两把 per-course 锁/原子写/质量迁移/空工作区/mind_map 读写 |
| backend/app/routers/deps.py | 282 | get_connection（主库 WAL）、归档辅助、permanently_delete_course_data（L113 清 data 目录+15 张表+向量缓存） |
| backend/app/main.py | — | initialize_database（courses/plan_tasks/archived_items/app_metadata） |
| backend/app/agent_runtime.py | — | initialize_agent_database（8 表 + ALTER 迁移） |
| backend/app/strategy.py | — | 策略 md 存储 strategy/review-plan.md、course-prompt.md + history/-vNNNN.md |
| backend/app/tenancy.py | 51 | owner 列迁移与遗留认领 |

## 调用链

router → study_service.load_workspace（门面，实体在 workspace.py）→ json.loads → 缺省补齐+质量迁移（有变更回写）→ save_workspace → per-course RLock → revision/planRevision 递增 → `_atomic_write_text`（tmp+os.replace）。SQLite：deps.get_connection → 各表；内容生成另有 `_content_generation_lock`。

## 数据契约

- workspace.json 顶层：course / onboarding{status: draft→diagnostic→strategy-review→planned} / modules / knowledgePoints / tasks / practiceQuestions / mockQuestions / practiceAnswers / mockResult / wrongAnswers / note / materialMemory / strategyDocuments{reviewPlan, coursePrompt{path,version,…}} / **revision / planRevision / planStartDate / timeLog** / schedulingWarnings / generationWarning / readabilityReview / **workspaceContentVersion** / optionShuffleMigrated 等
- SQLite 布局：data/exam_booster.db（主库多域表）+ data/embedding_cache.db（向量）+ courses/ 目录树（workspace.json、mind_map.json、strategy/*.md、material_cache/）
- API：GET/PUT /api/courses/{id}/workspace、GET/PUT /mind-map、POST /mind-map/generate、POST /mind-map/regroup-modules、POST /api/courses、DELETE /api/courses/{id}、GET/DELETE /api/archive/{id}、POST /api/archive/{id}/restore

## 测试锚点

test_facade_exports.py（paths 接线 + workspace 门面 33 符号 + 环检查）、test_time_log_idempotency.py、test_archive_purge.py、test_explicit_course_identity.py、test_multi_tenant_isolation.py、test_study_scheduler.py:636（内容质量守卫）、test_mock_questions_repair.py（expected_revision 守卫）

## 上游调用方 / 下游消费方

- workspace 依赖 paths、复习调度器（is_orientation）、课程生成流水线（单选重洗）；deps 被全部 router + main + tenancy 依赖
- 全部业务域的持久化终点

## 导读

读序：paths.py（23 行）→ workspace.py 的 load/save 与两把锁 → deps.permanently_delete_course_data（删除链路全貌）。理解双存储分工是理解本项目数据流的前提。
