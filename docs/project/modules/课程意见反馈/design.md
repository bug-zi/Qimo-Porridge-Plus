# 课程意见反馈（course-feedback）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

划词反馈的完整生命周期：反馈 → AI 分析与改写提案 → 预览确认 → 应用到讲义 → 偏好规则沉淀注入后续生成。含小节整体修改（AI伴学侧入口复用本域 global 端点）。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 服务端权威 proposal | refine/apply 只信持久化的 rewriteSession.latestProposal；请求体字段仅兼容保留——防伪造/篡改 |
| 规则确认制 | 规则生成即 proposed，仅勾选"记住偏好"才 active；summary prompt 只聚合 active 前 12 条；abandon 反激活——防未确认反馈污染生成（2026-08-28 bug 教训） |
| 删除即空改写 | 意见含"删除/删掉/去掉"直接返回 rewrittenText="" 预览，不调模型——删除预览显式可见 |
| 反馈永不因模型失败丢失 | 分析/提案失败落库（analysisError/rewriteError），201 语义保留，前端 partial-success 可重试 |
| 8 轮上限 + 会话压缩 | accept/abandon 后只留最后 2 条 attempt 元数据并删 latestProposal |
| 幂等与并发 | apply 幂等（accepted 已存在 → idempotent:true）；expected_revision 不符 → 409；小节级另有 guide sha256 token 防过期 |

## 不变量

- status 链：pending_analysis → analyzed → awaiting_confirmation → accepted/abandoned/expired
- 存储每课程独立：feedback.jsonl（原子重写）+ optimization_rules.json（rules≤24 / strongDirectives≤40 / summaryPrompt≤5000）
- 应用走 6 级替换链（fragments→story_section→exam_point→worked_example→concept→scope_fallback）+ `_build_study_guide_sections` + expected_revision 保存，跨字段事务可回滚
- 全部端点 Depends(require_course_ownership)；ValueError→422，冲突→409

## 禁区

- 不许跳过预览直接 apply；不许用请求体里的 previous_rewrite 覆盖服务端权威提案

## 设计异议

（无）
