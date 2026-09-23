# 模拟卷（mock-exam）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

课程模拟卷的组卷消费、作答计分与 AI 修复：选择题按 answerIndex 判分（经解析-答案一致性校验），计算题走 AI 批改；修复在生成锁内做增量合并，不覆盖并发学习更新。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 修复持 expected_revision=修复前 revision，在 `_content_generation_lock` 内执行 | 并发学习更新不被慢修复覆盖（revision 守卫） |
| 非 force 且 `mock_questions_need_repair` 为 False 时短路 | 不做无谓重生成，source="existing" 如实返回 |
| 计算题 AI 批改（earnedScore 钳制 0..满分；correct 或 ≥80% 判对；异常子串匹配兜底） | 主观题可机判；兜底只在 AI 异常时用文本匹配 |
| 选择题经 `reconcile_question_answer` 后判分 | 解析-答案冲突自动纠正后再判（2026-08-28 bug 教训） |
| MockView 自动修复一次（automaticRepairStartedRef 防重） | 空卷开箱即用但不重复触发 |
| 草稿 localStorage 与 mockResult 互斥 | 有成绩以成绩为准，草稿仅未提交时有效 |

## 不变量

- 选择题存 index、计算题存文本（MockAnswer=number\|string）；草稿键 `mock-draft:<courseId>`
- 每题判分联动 `_update_mastery`（对 +8 / 错 -3，0-100 钳制）与 `_prioritize_tasks`；失分写错题本（mode="模拟卷"）
- 提交成功后 `mark_strategy_maintenance_pending` + maintain_review_plan 入队

## 禁区

- 不许绕过 revision 守卫直接写 mockQuestions；不许删除一致性校验步骤

## 设计异议

（无）
