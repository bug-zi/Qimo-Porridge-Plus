# 顶部栏（topbar）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| web/src/components/TopbarCourseTimer.tsx | 74 | 计时器 UI |
| web/src/hooks/useCourseTimer.tsx | 251 | CourseTimerProvider Context + localStorage 待提交队列 |
| web/src/App.tsx | — | CourseSwitcher(L246-391)、QuickBackToTopButton(L216)、搜索弹窗(L2120-2192)、顶栏 JSX(L1924-2006) |

## 结构链

L1945 `<TopbarCourseTimer activeCourseId activeCourseName>` 于 header.topbar；L1907 CourseTimerProvider 包住整个 app-shell（onRecordMinutes=handleRecordMinutes / onFlushMinutes=flushCourseTimeLog / finalizeRef）。自动结算在 activeCourseId 变化（L159-165）；pagehide flush（L226-238）。

## 数据契约

POST /api/courses/{id}/time-log（api.ts:745，client_entry_id 幂等）、flushCourseTimeLog keepalive（L762）；TimeLogEntry（types.ts:879）、DailyProgress（L897）。handleRecordMinutes 合并 timeLog/dailyProgress（复习计划域数据）。

## 测试锚点

无。

## 上游调用方 / 下游消费方

依赖复习计划域（timeLog/dailyProgress 合并）、账户与登录（pending 队列按 userId 分键）、设置域（面包屑消费 modelProfile.status）。

## 导读

计时核心全在 useCourseTimer.tsx 一个文件；改时长记录先对齐后端 1-1440 校验与幂等键。
