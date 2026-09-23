# 顶部栏（topbar）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

顶部区域：课程计时器（自动计时 + localStorage 待提交队列）、面包屑、课程切换器（CourseSwitcher 内联于 App）、搜索弹窗、回顶按钮。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 计时走 CourseTimerProvider Context + localStorage 待提交队列 | 刷新/断网不丢时长；下次进入自动重试（键 `final-congee-course-timer-pending:{userId}`） |
| 自动计时：activeCourseId 变化即结算旧段开新段 | 课程切换边界即计时边界 |
| pagehide keepalive flush + logout 前 finalizeRef 兜底 | 尽量不丢最后一分钟 |
| 整分钟粒度，MAX_RECORD_MINUTES=1440 | 后端校验 1-1440 对齐 |

## 不变量

- 计时 API：POST /api/courses/{id}/time-log（client_entry_id 幂等）+ flush keepalive 版
- 退出计时 discard 仅手动重启生效

## 禁区

- 计时逻辑不进 ModuleView（保持 Provider 全局单例）

## 设计异议

- useCourseTimer 的 `backfill` 已暴露但**无消费者**——待开发者裁决删除或接入
