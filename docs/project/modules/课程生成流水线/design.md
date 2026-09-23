# 课程生成流水线（content-pipeline）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层：只写决策与红线；实现事实见同目录 `designs-specs.md`。

## 定位

策略文档批准后的一轮课程内容生产引擎：规划 → 逐节（讲义初稿→patch→自测→patch→合并）→ 模拟卷 → 第0天导引 → 排版审核。以 job 形式在后台队列执行，逐节增量预览落盘工作区。用户不可见，是复习主线域的内容来源。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 显式失败优于低质成功 | 历史决策（c66dea6 移除降级处理）：规划/讲义/自测硬伤 patch 一次后仍硬伤直接 raise，禁止凑合内容假装成功 |
| checkpoint 签名缓存 | `stable_signature`（sha256+排序 JSON）+ 契约版本常量；命中即跳过模型调用，升版即全量失效旧缓存（story 模板升 v6 即此机制） |
| 无初稿不 patch | 无有效 checkpoint 必须先完整生成自测；patch 的 add_question 不带 examPointIds 必致覆盖校验失败（2026-08-29 bug 教训，见错误档案） |
| 软硬伤拆分 | 数量/顺序/措辞类软伤接受不重生成；事实类硬伤必须 patch 修复后放行 |
| 失败留痕不覆盖 | lesson_guide_failed 每次尝试新 version 留档；取消时清半成品 checkpoint |
| partial 如实标记 | 缺讲义节标 contentQualityWarning；partial_errors 进 ReviewReport(passed=False)，前端如实提示 |
| 风格模板版本化 | course_style_templates：standard(v1)/dialogue(v1)/story(v6)，模板 version 进入内容签名 |

## 不变量

- examPointIds 覆盖：计算/证明/应用考点须例题覆盖；每考点 ≥1 自测题；覆盖校验只认 examPointIds 字段
- 解析一致性：`reconcile_question_answer` 先于选项洗牌执行
- patch path 用点号+下标格式（JSON Pointer 斜杠格式归一化等价接受）；深度 ≤8；op 白名单；禁改 id/taskId/knowledgePointId/source
- 模型全不可用立即中止整轮；repair_only 不重排计划且跳过每日预算校验
- 第0天导引靠 kind 判重幂等注入

## 禁区

- 不许加回"失败时返回降级模板凑合内容"的逻辑（lesson_fallbacks 仅门面保留，主线不调用）
- 不许绕过硬校验直接落盘；不许在生成链路吞异常后继续

## 设计异议

（无）
