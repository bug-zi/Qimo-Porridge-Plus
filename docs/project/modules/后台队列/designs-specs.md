# 后台队列（job-queue）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| backend/app/agent_runtime.py | 1223 | 队列核心：enqueue/_claim/_complete/_fail/_renew/心跳/ownership/progress/AgentJobWorker/建表迁移(L57-260) |
| backend/app/main.py | 306 | L105 注册 6 个 handler；lifespan start/stop；5 个 job 函数 |
| backend/app/external_source_service.py | 153 | external_source_import 处理器 |
| backend/app/routers/agent.py | 107 | job/run 查询与取消端点 |
| backend/app/model_usage.py | 117 | get_scoped_model_usage（job 结果附带用量） |

## 调用链

入队：6 个 router（materials/practice/courses/strategy/glossary/external_source）→ `enqueue_agent_job` → agent_jobs 表。执行：lifespan → `AgentJobWorker._run` → `_claim_job`（BEGIN IMMEDIATE + 过期 lease 回收 + 同课程互斥 + 优先级）→ handler 子线程（payload 注入 _jobId/_leaseToken）→ `_complete_job`/`_fail_job`；心跳 60s 续租。取消：`cancel_agent_job` + handler 内 `is_agent_job_cancelled`/`has_agent_job_ownership` → AgentJobCancelled。

## 数据契约

- agent_jobs 表：id/course_id/job_type/payload_json/status/attempts/max_attempts(默认3)/available_at/lease_until/**lease_token**/error/result_json/**progress_json** + idx_agent_jobs_ready
- API：GET /api/agent-jobs/{job_id}、POST /api/agent-jobs/{job_id}/cancel（仅 approve）、GET /api/agent-runs/{run_id}
- 同库还有 agent_runs/agent_steps/artifacts/adjustment_proposals/external_sources/glossary_terms/glossary_refresh_state/mcp_servers

## 测试锚点

test_agent_job_queue.py（11 用例）、test_mainline_generation_repair.py:226/272

## 上游调用方 / 下游消费方

- handler 实体在 study_service/review_plan/external_source_service；被 7 个 router 反向入队；任务级取消点 `has_agent_job_ownership` 接入课程生成流水线

## 导读

读序：agent_runtime.py 的 `_claim_job`（L574 起，互斥+fencing 精华）→ `_lease_heartbeat`（L680，异常保护）→ main.py handler 注册表。改队列行为前必读 2026-08-28 双重执行事故的错误档案。
