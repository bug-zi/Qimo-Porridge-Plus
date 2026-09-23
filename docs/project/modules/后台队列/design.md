# 后台队列（job-queue）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

SQLite 持久后台任务队列：job 入队/认领/执行/取消、lease fencing、心跳续租、进度上报。单进程单线程 worker（AgentJobWorker），**禁止开多个 uvicorn worker**（CLAUDE.md）。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| lease fencing 代际 token | claim 时生成新 uuid；complete/fail/renew/progress 全部 `WHERE lease_token=?`，旧代写入被拒——根治 2026-08-28 心跳猝死→lease 过期→二次 claim→同课程双份生成事故 |
| 同课程互斥（NOT EXISTS 同 course running） | 课程级串行，杜绝并发生成互踩 workspace |
| 心跳单次 sqlite3.Error 不猝死 | 心跳线程异常保护，防止再次引发 lease 过期连锁事故 |
| 2h 硬超时弃线程标失败 | 线程不可强杀；宁可弃线程也保证队列不卡死 |
| job_type 优先级 | approve(课程生成)=0 > import=1 > orientation=2 > glossary=3 > maintain=4 > rebalance=5 |
| 失败退避 `min(60, 2**attempts)` | attempts 耗尽→failed；幂等复用同 course+type 的 active job |

## 不变量

- status ∈ queued/running/completed/failed/cancelled；cancelled 不可被 complete 覆盖；`_fail_job` 对取消直接 return
- `wait_for_generation_lock=True` 排队共享锁而非误报失败
- 业务完成度随 result 返回（contentComplete/partial）
- 入队白名单仅 6 种 job_type

## 禁区

- 不许多 worker 并发消费；不许移除 lease_token 校验"简化"写入路径

## 设计异议

（无）
