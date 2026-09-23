# 错题本（wrong-book）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

错题记录、AI 举一反三、重做判分、软归档。错题来源五个场景（摸底/主线/刷题/模拟卷/错题重做），删除即 7 天可恢复的软归档。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 重复错题按 id 去重累加 count，重置 isReviewed=False | 同一弱点反复错要显式可见 |
| AI 举一反三新题入 practiceQuestions 池（id=ai-similar-{baseId}-{sha1[:10]}，id+prompt 双重去重） | 变式题复用刷题判分链路 |
| AI 失败回退 base_analysis 且 added_count=0 | 显式降级为"仅解析"，不假装生成了新题 |
| 计算题错题（_record_written_wrong_answer）不触发 AI | 主观题变式生成价值低、成本高 |
| 重做正确后触发复习计划维护 job | 弱点消除应反映到计划 |
| 删除即软归档（archived_items，7 天恢复） | 复用课程归档通道，防误删 |

## 不变量

- `diagnostic-` 前缀 id 双重回退解析（先 questionId 去 prefix，再 wrong_answer_id 去 prefix）
- 原题被题库更新移除时前端显示"原题已不在当前题库"保留记录
- mistakeType 字段实际存 AI 解析文本（历史命名，勿被名字误导）

## 禁区

- 不许物理删除错题记录（一律走归档通道）

## 设计异议

- 无独立错题测试文件（打桩经 study_service 命名空间，由 test_facade_exports 覆盖 re-export）——测试覆盖偏薄，待开发者裁决是否补
