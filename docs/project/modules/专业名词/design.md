# 专业名词（glossary）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

课程术语库：两阶段生成（Scanner 扫候选 → Curator 分批撰写词条）、正文划词正则匹配高亮、悬停卡片。SQLite 持久（glossary_terms），增量刷新带内容签名缓存。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 两阶段生成 + 阶段1 checkpoint（签名缓存） | 资料未变时刷新短路 skip，不重复烧模型 |
| 候选校验（20-120 条、term≤60 字、casefold 去重）失败重试 1 次 → 兜底用知识点名 | 保底可用而非失败 |
| 候选 >90 只写 core 档，截断上限 150 | 控制高亮密度与模型成本 |
| upsert 不变量：origin=manual 永不被 curator 覆盖（仅合并别名） | 用户手输词条神圣 |
| 增量失活：上轮词条不在本轮候选 → inactive | 术语库随资料演进，不删只失活 |
| 前端匹配：最长别名优先、拉丁别名边界守卫、单字母剔除、正则 >2500 只留 core、跳过 CODE/PRE/A/KBD/katex | 性能与渲染安全 |

## 不变量

- importance ∈ core\|extended；status ∈ draft\|active\|inactive；match_key UNIQUE(course_id, match_key)
- 资料上传/角色变化自动触发刷新（routers/materials）
- GlossaryProvider 1.5s 轮询至 ready

## 禁区

- curator 生成不得覆盖 manual 词条

## 设计异议（来自用户草稿区，待开发者确认状态）

- 用户曾记：「当前只有重新生成按钮——但需要的是初步生成；希望可自由编辑（增/删/语义查找）」——代码已有 update/delete 端点（origin=manual），**草稿诉求部分已落地**，请开发者验证后裁决关闭或保留
- 生成机制准确性「有待验证」——同上待确认
