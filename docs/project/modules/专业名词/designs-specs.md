# 专业名词（glossary）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| backend/app/agents/glossary.py | 564 | 两阶段生成（Scanner→Curator） |
| backend/app/agent_runtime.py | — | glossary_terms/glossary_refresh_state 表、upsert/list/update/delete、match_key、refresh_state |
| backend/app/routers/glossary.py | 118 | 5 端点 |
| backend/app/study_service.py | — | run_glossary_refresh_job(L1111)；main.py worker 注册(L87-111) |
| web/src/hooks/useGlossary.tsx | 185 | GlossaryProvider 轮询 |
| web/src/glossary/termMatcher.tsx | 154 | 正则包裹器 |
| web/src/components/GlossaryTermSpan.tsx / GlossaryTermCard.tsx | 93/82 | 悬停词条/卡片 |
| web/src/components/ModuleView.tsx | — | GlossaryView(L5581) |

## 调用链

POST /glossary/refresh → enqueue glossary_refresh → `run_glossary_refresh`（阶段1 扫候选 L306 → 阶段2 分批 10 条撰写 L398 → upsert 增量合并 → 失活 stale）。前端：App L1906 GlossaryProvider 包全树 → GlossaryView 进页自动 refresh + 1.5s 轮询；正文注入 setActiveGlossaryTerms → FormulaText/glossaryMarkdownComponents → wrapTextWithTerms → GlossaryTermSpan（300ms 悬停 tooltip）。

## 数据契约

- glossary_terms：term、match_key UNIQUE(course_id,match_key)、aliases_json、one_liner、article、exam_tips_json、pitfalls_json、importance core\|extended、status draft\|active\|inactive、origin curator\|manual
- glossary_refresh_state：status idle\|generating\|ready\|failed、content_signature、phase、candidates_total、terms_completed…
- API：GET /glossary、GET /glossary/status、PUT/DELETE /glossary/terms/{term_id}、POST /glossary/refresh{force}；TS GlossaryTerm/GlossaryStatus（types.ts:908-943）

## 测试锚点

test_glossary_progress.py（refresh_state 列迁移 + round trip）

## 上游调用方 / 下游消费方

- 依赖：RAG检索（sample_material_chunks 采样）、后台队列、workspace（知识点/模块标题作输入）
- 下游：复习主线/笔记等全部 Markdown 渲染（termMatcher 包裹）；资料变化自动触发

## 导读

读序：glossary.py 两阶段 → upsert_glossary_term 的 manual 保护逻辑 → termMatcher 匹配规则。
