# agent_chat 缺 import 导致 Tutor Agent 工具循环不可达

- 档案号：2026-09-24-agent-chat-tutor-unreachable
- 发现时间：2026-09-24 01:40（文档逆向调研中静态发现）
- 严重度：高
- 所属域：AI伴学（agent_chat.py / tutor）
- 发现场景：AI伴学域 design.md 起草前的代码调研（subagent 报告 + 主会话 grep 复核确认）
- 错误现象：`agent_chat.py` L484 调用 `run_tutor_agent_stream`、L686 调用 `run_tutor_agent`，但该模块的 import 区（仅 json/re/datetime/typing/knowledge_service）不含这两个名字；运行时必然 NameError
- 导致后果：NameError 被两处宽 `except Exception`（L506/L691）吞掉后恒走"降级一次性 RAG 回答"分支——**Agent 工具循环（search_materials/fetch_web_page 等工具）在流式与非流式两条路径上均实际不可达**；用户侧表现为 AI 伴学永远只有普通 RAG 问答能力
- 根因：2719755（阶段2-7）从 study_service 抽取 agent_chat.py 时，`from .agents.tutor import run_tutor_agent(_stream)` 漏带；import 只存在于 study_service.py 的另一命名空间，无 setattr 注入
- 建议修复方式：agent_chat.py 补 `from .agents.tutor import run_tutor_agent, run_tutor_agent_stream`（或经缝合点延迟 import 以保住既有打桩面）；补一个"agent 模式触发工具循环"的回归测试；顺手排查两处宽 except 是否应收窄
- 状态：🔴 待修复（项目处学习/冻结期，先建档；修复待开发者决策）
- 关联：看板 🐛 区同日条目；AI伴学域 design.md 设计异议节
