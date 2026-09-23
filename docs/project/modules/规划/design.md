# 规划（planning）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

策略文档（复习总计划 + 课程 Prompt）的生成/审阅/版本化/草稿修订。三 Agent 顺序生成（Knowledge Curator → Strategy Planner → Course Prompt Architect）产出 Markdown 文档，审阅批准后触发课程生成流水线。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 纯文件存储（strategy/*.md + history/-vNNNN.md） | 计划全文是人读人改的文档，不进 DB；history 每版本留档 |
| 版本乐观锁 | expected version 不符 → 409"已被更新"；每次写入版本 +1 并同步写 history |
| 三段定界标记解析（REPLY/REVIEW_PLAN/COURSE_PROMPT） | 缺段即 error，绝不返回半份草稿 |
| 草稿修订不落盘不写记忆 | 纯草稿对话（SSE 流式打字机），保存才生效 |
| 打字机只转发 reply 段 + 标记长度缓冲 | 防定界标记半个外泄到 UI |
| 课程顺序硬合同 | 重要程度只控详略，不改主线顺序 |
| 批准入后台 job（approve-job 202） | 生成耗时长，走队列最高优先级，前端轮询 |

## 不变量

- status ∈ generating / review / approved / maintenance-error；只有 approved 才允许维护标记
- `_validate_strategy_content` 拒绝空内容
- workspace.strategyDocuments 只存元数据（path/version/updatedAt/updatedBy/changeSummary），不存全文

## 禁区

- 不跳过版本锁直接覆盖写；不得丢弃 history 链

## 设计异议

（无）
