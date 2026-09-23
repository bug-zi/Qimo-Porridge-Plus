# 模型调用（model-client）域规格 specs

> 状态：🌱 AI 从代码生成，随代码同步 ｜ 生成日期 2026-08-29
> 事实以代码为准；与代码冲突时更新本文，不反过来。

## 导读（写给人）

**本域管什么**：把 prompt 变成模型响应的一切网络与容错细节。你看到的每一次
"AI 生成中"（课程、对话、批改、连通性测试），底层都经过这里。

**一条典型调用链**（以课程生成的讲义阶段为例）：

```
content_workflow.scoped_model_json("lesson")
  → model_json(task_prompt, user_content, course_prompt)      model_client.py:596
  → _model_completion(...)                                     :543  拼payload/选provider/重试/failover
    → _model_providers()                                       :233  [主模型, 备用模型(如配)]，含熔断
    → _provider_request(provider, payload, stream=True)        :273  构造 requests.Request
    → _open_model_stream / _read_sse_response                  :394/:664  流式读取，30s 首 token 判死
  → _extract_json(content)                                     :835  从模型文本鲁棒抽 JSON
  → 返回 dict 给业务层
```

**常见困惑**（学习中问到就补到这里）：
- 为什么有三种入口？——JSON 任务（大多数生成）/agent 轮次（伴学对话，带工具表）/流式（SSE 直通前端）。
- 重试和 failover 什么关系？——单 provider 内先按退避重试（`_transient_retry_delay`），
  重试预算耗尽换下一个 provider；全没了才报"均不可用"。
- 设置页"测试"按钮走哪？——`probe_model_chat`（:342），独立于业务入口，带自己的超时。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| `backend/app/model_client.py` | 770 | 全部模型调用逻辑（本域主体） |
| `backend/app/model_usage.py` | — | 调用遥测：record_call_start/result、model_call_scope、get_model_usage |
| `backend/app/model_profiles.py` | 311 | 运行时/备用模型配置与用户画像（.env 读写）、build_model_messages 注入 |
| `backend/app/routers/settings.py` 部分 | — | runtime-model / backup-model / model-profiles/test 路由 |

## 入口与调用链

三种业务入口 → `_model_completion` → provider 链 → SSE 读取。
辅助入口：`probe_model_chat`（连通性测试）、`fetch_available_model_ids`（模型列表发现）、
`parse_available_model_ids`。配置：`_read_runtime_env` / `_read_backup_model_env` /
`get_backup_model_profile` / `save_backup_model_profile`。

**上游调用方**（谁在用本域）：
- `agents/` 全部工作流（content_workflow、lesson_generation、question_generation、tutor、glossary…）
- `agent_chat.py`（伴学对话）、`strategy.py`（策略文档生成/修订）
- `material_parser.py`（视觉兜底解析，直接 import `_model_completion`）
- `study_service.py:71` 门面 re-export（保持历史 import 路径兼容）

**依赖注入点**：`model_profiles.py:147` 的 `set_message_builder(build_model_messages)`。

## 数据契约

- 入参：`(task_prompt: str, user_content: str, course_prompt: str = "")` → `dict`
- 流式入口：`(messages: list[dict], tools: list[dict])` → 模型轮次结果
- `.env` 键：主模型（base_url/api_key/model）+ `BACKUP_*` 备用组；丢失即全失效
- 遥测结构：model_usage 按 job/run/stage/task 维度聚合（前端 Token 用量展示的数据源）
- 熔断状态：进程内（`_note_provider_result`），不持久化

## 测试锚点

- `backend/tests/test_model_client.py`：fake-provider 单测 ×7（流式/首 token 超时/重试/failover，阶段1-4）
- 验证基线：后端全量 187 passed（2026-08-29）

## 设计异议

（无——发现 design 与代码不符时记此处，交用户裁决）
