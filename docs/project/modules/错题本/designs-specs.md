# 错题本（wrong-book）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| backend/app/practice.py | — | `_record_wrong_answer`(L315)、`_ai_review_wrong_answer`(L239，举一反三)、`_normalize_generated_practice_questions`(L181)、`_record_written_wrong_answer`(L131，计算题版不触发 AI)、`submit_wrong_answer_retry`(L452)、`_find_any_question`(L39，跨三题库找原题) |
| backend/app/routers/practice.py | 206 | retry_course_wrong_answer(L138)、archive_course_wrong_answer(L126) |
| backend/app/routers/deps.py | 282 | create_archive_item(L238)、ARCHIVE_RETENTION_DAYS=7 |
| web/src/components/ModuleView.tsx | — | ErrorsView(L4239，列表+重做详情；L4325"原题已不在当前题库") |
| web/src/api.ts | — | submitCourseWrongAnswerRetry(L675)、deleteCourseWrongAnswer(L1136) |

## 调用链

重做 POST /wrong-answers/{id}/retry → `submit_wrong_answer_retry` → reconcile_question_answer → 判分 → 对则 isReviewed=True，错则 `_record_wrong_answer`（AI 解析 + 同考点新题入 practiceQuestions）。归档 DELETE /wrong-answers/{id} → `create_archive_item(item_type="wrong-answer")` 同时从 workspace 移除。前端 ErrorsView 挂载于 L5849。

## 数据契约

- workspace `wrongAnswers[]`：{id,questionId,questionType(五场景),source,addedAt,reviewedAt,title,tag,mistakeType(存 AI 解析文本),count,isReviewed}；TS WrongAnswer（types.ts:459）
- archived_items 表（payload JSON，purge_after=deleted_at+7 天）；响应 {workspace, archive_item}

## 测试锚点

test_facade_exports.py（错题函数 re-export 与成环检查）；无独立错题测试文件。

## 上游调用方 / 下游消费方

- 依赖：刷题域（掌握度/优先级联动复用）、模型调用（举一反三与解析）、归档域、后台队列（维护任务）
- 下游：模拟卷报告页"去错题本"按钮、前端 onModuleChange('practice') 定向复练

## 导读

读序：practice.py 错题段 L131-L452 自上而下 → ErrorsView。找原题逻辑 `_find_any_question` 跨 practice/mock/diagnostic 三库，改题库结构时必查。
