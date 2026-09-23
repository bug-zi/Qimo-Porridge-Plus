# AI伴学（ai-companion）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| backend/app/agent_chat.py | 754 | 记忆提炼/滚动摘要/消息组装/agent_chat(_stream)/_sse 序列化 |
| backend/app/routers/agent.py | 107 | chat、chat/stream、agent-runs/agent-jobs 查询与取消 |
| backend/app/agents/tutor.py | 265 | run_tutor_agent(_stream) 工具循环，MAX_TUTOR_STEPS=8 |
| backend/app/agents/tools.py | 1019 | TOOL_DEFINITIONS/execute_agent_tool |
| backend/app/knowledge_service.py | — | chat_turns/chat_summaries/learner_memories + 检索 |
| web/src/components/AiCompanion.tsx | 770 | aside.ai-panel 双面板（chat/agent + 笔记切换、小节整体修改多轮编辑器、proposal 卡） |
| web/src/api.ts | — | askCourseAgent(L784)、streamCourseAgent(L870)+parseAgentSseEvent(L822) |

## 调用链（SSE）

AiCompanion.sendMessage → App handleAgentMessage（乐观消息+token 缓冲节流）→ streamCourseAgent（authFetch+ReadableStream 按 \n\n 分帧）→ POST /agent/chat/stream → `agent_chat_stream` → `_build_agent_messages` → `run_tutor_agent_stream`（yield step/token/tool_start/tool_end/done）→ `_sse`。done 在写库之后。收尾：record_chat_turn → _summarize_chat_memories（触发词正则，LLM 提炼 ≤4 条）→ _maintain_rolling_summary → workspace.messages 追加。

## 数据契约

- chat_turns（external_id UNIQUE、conversation_mode chat\|agent、sources_json）；chat_summaries（from/to_turn_id）；learner_memories（memory_type ∈ weak_point/goal/preference/progress/fact、confidence、id=sha256(course|type|kp|content)）+ memory_evidence
- workspace.messages：{id: user-{ts}/assistant-{ts+1}, role, mode, content, toolEvents?, sources?}
- 端点：POST /agent/chat、POST /agent/chat/stream（body {message, mode, context?}）、GET /api/agent-runs/{run_id}
- SSE done data：{reply, proposal, sources, runId, toolEvents, workspace}

## 测试锚点

test_facade_exports.py:276-299（agent_chat re-export 同一对象 + 不 import study_service 环检查）；test_model_client.py（假 SSE server 覆盖底层流式）。/agent/chat 端点无直测。

## 上游调用方 / 下游消费方

- 依赖：study_service（模型三函数、prompt 组装、workspace）、knowledge_service（9 符号）、agent_runtime（agent_run）、课程意见反馈（global 三端点）、规划（strategyReviewActive 接管面板）、复习调度器（_review_session_days）
- 前端装配：App.tsx L2090-2114

## 导读

读序：agent_chat.py 顶部缝合点注释 → _build_agent_messages（组装顺序即产品行为）→ tutor.py 工具循环 → AiCompanion 的 global 修订三函数（L378-441）。**注意已建档缺陷**：工具循环当前因缺 import 不可达，修复前读 tutor.py 仅为修 bug 服务。
