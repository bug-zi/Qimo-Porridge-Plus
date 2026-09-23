# AI伴学（ai-companion）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

侧边 AI 对话：chat/agent 双模式、SSE 流式、滚动摘要与分层记忆、工具循环（Agent 模式）、"整体修改当前小节"多轮对话（复用课程意见反馈域 global 端点）。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 缝合点纪律：agent_chat 模块级禁 import study_service，函数内延迟 import | 防循环导入 + 保住 monkeypatch 打桩面（test_facade_exports 有环检查） |
| 滚动摘要：最近 8 条原文不压缩，每次压最老 8 条为 ≤140 字脉络；某批失败即中断 | 防 to_turn_id 空洞；全程静默降级 |
| 分层记忆 build_conversation_memory | recent(8 条) + summary 拼接 + 词法相关史（exclude_recent=8 之外 ≤4 条） |
| 消息组装顺序固定：system(平台守则+工具守则+LaTeX) → 自画像 → 课程偏好 → 界面上下文(仅消解指代) → 早期脉络 → recent → 本轮 | 工具/网页输出视为不可信数据 |
| 提案制 | 任务/计划调整只能经 propose_plan_change 生成 pending 提案，不得声称已修改 |
| 流中断降级 | generator 抛错 → 降级一次性 RAG + warning；前端 onError 再用非流式兜底 |

## 不变量

- SSE 事件序：token/step/tool_start/tool_end/warning/done/error；done 在写库 + save_workspace 之后发出，data 含最终 workspace/proposal/sources/runId/toolEvents
- chat_turns 双写（external_id UNIQUE 幂等）；rolling summary 失败不产生空洞
- 切换任务/小节时小节修改会话重置（useEffect L317-323）
- refine 只传 feedbackId+extraComment，历史意见与上一版候选由服务端从 session 重建

## 禁区

- Agent 模式不得直改 workspace（只能提案）
- 宽 except 不得扩大使用范围（见异议缺陷）

## 设计异议

- 🔴 **已建档缺陷**（2026-09-24-agent-chat-tutor-unreachable）：agent_chat.py 缺 `run_tutor_agent(_stream)` import，NameError 被吞 → Agent 工具循环实际不可达，恒走降级 RAG。待开发者决策修复
- `/agent/chat` 端点无直测（仅门面 re-export 与环检查覆盖）——测试缺口待裁决
