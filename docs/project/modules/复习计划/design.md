# 复习计划（review-plan）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

总计划的日常维护层：AI 维护复习计划文档、每日进度计算、时长记录、顺延/减负/重排提案、工作台手动调整。是复习调度器结果的消费者与维护者（自己不直接重排，重排只经调度器函数）。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 维护写前重查版本，漂移则置 maintenancePending 不覆盖 | 防止 AI 维护覆盖用户手工成果 |
| tasks 状态压缩后送模型（~2MB→KB 级） | 防模型网关 502 |
| completed 与导引任务绝对禁改 | 已学内容与第0天导引神圣不可侵犯 |
| 提案 baseRevision 过期不硬拒，任务存在性才是校验点 | 提案生命周期与编辑并发解耦 |
| DAG 只拒绝"相对基线新增违规" | 允许存量违规暂存，阻止恶化 |
| 超额自动入队 rebalance，冷却 30 分钟 | 防提案风暴 |
| 复习日分布公式前后端双实现必须同步 | study_service._review_session_days ↔ reviewSchedule.ts，银行家舍入差异注释 |

## 不变量

- operations 白名单：move_task/change_duration/change_priority；day 1-30、minutes 5-720、时长记录 1-1440 分钟
- todayDay 由 planStartDate + 当前日期推导，clamp [1, maxDay]
- timeLog 幂等：client_entry_id 去重
- 仅改考试日期走轻量 update_course_plan_params；改天数/时长走 replan_review_mainline（同步，失败 502）

## 禁区

- 不绕过调度器函数直接改 tasks 的 day/order
- AI 维护不得覆盖 approved 版本（版本漂移只标记，不写）

## 设计异议

（无）
