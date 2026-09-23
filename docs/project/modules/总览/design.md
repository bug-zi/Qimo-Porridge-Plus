# 总览（overview）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

工作台首页：课程进度、今日任务、诊断指标展示。主要是复习计划域数据的渲染层，todayDay 过滤当日任务并给出学习入口。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| todayDay 不写死（L469 注释） | 由 dailyProgress（planStartDate 推导）驱动 |
| onboarding 分流：strategy-review→策略审核，非 planned→引导，诊断回顾→结果页 | 总览是课程生命周期各态的集成分发口（ModuleView L5785-5833） |
| 任务乐观更新 + PUT 对账 | 后端 DAG 修复会顺延，本地先动、以服务端为准 |

## 不变量

- 渲染数据全部来自 workspace.tasks / dailyProgress / pendingProposals（复习计划域产物）
- courseProgress=tasks 进度均值、completedTasks 由 App 计算（L804/810）后下发

## 禁区

- 总览不自算调度/进度口径（一律消费复习计划域产物）

## 设计异议

（无）
