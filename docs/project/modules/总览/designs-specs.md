# 总览（overview）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| web/src/App.tsx | 2210 | L2008-2088 挂载 ModuleView（70+ props）；启动数据 Promise.all(L721-734)；courseProgress/completedTasks(L804/810)；任务乐观更新对账(L855-869) |
| web/src/components/ModuleView.tsx | — | OverviewView(L444-557，todayDay 过滤 TaskRow)+ 分派入口(L5785-5833)+ TaskRow/KnowledgeBars 子件 |

## 结构链

activeModule==='overview' 按 onboarding 状态分流：strategy-review → StrategyReviewView(L5820)；非 planned → CourseOnboardingView；诊断回顾 → DiagnosticResultView；否则 OverviewView（todayDay=dailyProgress.todayDay，渲染 day===todayDay 任务，onStudyTask 进入 StudyTaskView）。

## 数据契约

GET/PUT /api/courses/{id}/workspace；类型 StudyWorkspace(L794)/PlanTask(L437)/DailyProgress(L897)/KnowledgePoint(L707)。

## 测试锚点

无（ModuleView 5910 行零测试）。

## 上游调用方 / 下游消费方

- 依赖：复习计划（dailyProgress/pendingProposals）、复习主线（StudyTaskView 学习入口）、复习调度器（后端 DAG 修复顺延对账）、设置域（指标卡消费 diagnostic/assessmentProfile）

## 导读

两个入口文件；改总览先分清「App 计算的统计」与「后端 dailyProgress」两层口径。
