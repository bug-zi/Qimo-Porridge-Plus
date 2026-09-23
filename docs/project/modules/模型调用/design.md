# 模型调用（model-client）域设计

> 状态：🌱 AI 逆向起草，待用户审定 ｜ 起草日期 2026-08-29（学习/冻结期）
> 本域是全项目最核心的基础设施：所有 LLM 交互的唯一出口。

## 定位

把"调用一个 OpenAI 兼容模型"这件事的所有工程问题（超时、重试、failover、熔断、流式、
用量统计、JSON 抽取）收敛到一个模块，让上层业务（课程生成、对话、批改）完全不感知网络细节。

## 关键决策

1. **唯一出口**：全项目只允许 `model_client.py` 对外发模型请求。上层一律通过
   `_model_json`（JSON 任务）/`_model_agent_turn`（agent 轮次）/`_stream_model_turn`（流式）
   三入口使用。禁止任何模块绕过它直连 API。
   *理由*：用量统计、failover、超时策略只在这一处才能保证全局一致。
2. **流式 + 30s 首 token 超时**（阶段1 改造，5fe4a13）：非流式整包等待无法区分
   "上游挂死"与"思考型模型静默"，300s 总超时曾误杀正常慢请求造成假死循环。
   现策略：流式打开后 30s 无首字节判死，读流阶段不再用短超时误杀。
   *约束*：完成流式改造前不许单纯调小总超时（历史教训，CLAUDE.md 记载）。
3. **主备 failover + 熔断**：`_model_providers` 返回主模型→备用模型有序列表；
   `_note_provider_result` 记录成败用于熔断决策。重试预算内主模型不行切备用。
4. **显式失败**：全部 provider 耗尽时抛"主模型与备用模型均不可用"。调用方
   （content_workflow）捕获后**立即中止整轮生成**，避免剩余几十节课逐节空转、
   每节耗尽一遍重试预算。禁止低质量内容假装成功（项目级历史决策 c66dea6）。
5. **消息构造器注入**：`set_message_builder(build_model_messages)` 在 model_profiles
   导入时注入（model_profiles.py:147），model_client 不依赖用户画像细节——依赖倒置。
6. **用量遥测内建**：`model_call_scope`（model_usage）给每次调用打 job/run/stage/task 标签，
   阶段化成本可观测（效率优化的数据基础）。

## 不变量

- 任何模型 HTTP 请求只从 `_provider_request` 发出（含 probe 测试）。
- 首 token 超时只判"真挂起"，不得回归到"短总超时误杀慢思考"。
- "主备均不可用"必须向上传播为显式错误，不得静默降级。
- 备用模型配置（.env BACKUP_*）读写只经 get/save_backup_model_profile。

## 禁区

- 不做多 provider 并发竞速（单用户本地版无此需求）。
- 不引入 SDK 依赖，保持 requests 直连（现状，如要改走 proposals）。

## 设计异议

（无）
