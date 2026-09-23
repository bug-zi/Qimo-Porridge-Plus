# 模拟卷（mock-exam）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| backend/app/practice.py | 719 | `repair_course_mock_questions`(L535)、`submit_mock_answers`(L607) |
| backend/app/routers/practice.py | 206 | repair_course_mock(L154)、mock submit(L171) |
| backend/app/agents/question_generation.py | — | `mock_questions_need_repair`(L332)/`repair_mock_questions`(L347) |
| backend/app/agents/workflow.py | — | repair_mock_questions 兼容包装(L51，保 monkeypatch 面) |
| web/src/components/ModuleView.tsx | — | MockView(L3903)、草稿 readMockDraft/writeMockDraft(L3876/3894)、isWrittenMockQuestion(L3847) |
| web/src/App.tsx | 2210 | handleRepairMockGeneration(L1589)/handleMockSubmit(L1350)/handleClearMockResult(L1376) |

## 调用链

POST /api/courses/{id}/mock/repair → `repair_course_mock_questions` → study_service.repair_mock_questions（课程生成流水线域实现）；POST /mock/submit → `submit_mock_answers`。前端 MockView 挂载于 ModuleView L5843，apiClient 双实现（api.ts/demoApi）。

## 数据契约

- workspace：mockQuestions、mockResult{submittedAt,score,total,answers,results[]}、mockQuestionsGeneratedAt/GenerationSource/GenerationWarning
- 请求 MockSubmitRequest{answers: dict[str,int|str]}；TS：MockAnswer=number\|string、MockResultRecord（types.ts:864）
- 草稿 localStorage `mock-draft:<courseId>`

## 测试锚点

test_mock_questions_repair.py（fallback/幂等/revision 守卫/路由注册）、test_mainline_generation_repair.py（mockQuestions 增量合并）、test_facade_exports.py:216-249

## 上游调用方 / 下游消费方

- 依赖：课程生成流水线（题目生成与修复）、模型调用（计算题批改）、错题本/刷题（掌握度与优先级联动）、后台队列（维护任务）
- 下游：错题本（失分写入）、总览（成绩展示）

## 导读

读序：practice.py 的 mock 两函数 → question_generation.py 的 need_repair/repair → MockView。修复语义与刷题域共用 study_service 打桩面（延迟 import）。
