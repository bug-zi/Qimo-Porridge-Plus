# 复习主线（mainline）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

学习页主体：模块 → 任务 → 讲义/例题/自测的学习与生成入口。是课程生成流水线的内容落点（消费 workspace），也是多数学习交互（划词/笔记/反馈/AI伴学）的宿主页面。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 生成失败显式报错不降级 | 状态卡文案「服务端确认失败」「未将任务伪造为失败」；`classifyGenerationError` 归类展示（与后端显式失败原则对齐） |
| 视图切换用 if-return 分发而非路由 | 单页本地应用，ModuleView 顶层做纯路由分发器（~30 个 props 注入） |
| 排版保留审核、移除评分 | 70d6c72：单课/汇总 score 已删，但后端 readability_review 与讲义摘要卡保留 |
| KaTeX 双路渲染 | `renderKatexFormula`（throwOnError 失败返 null）+ 旧版正则降级 `renderLegacyFormulaInline`，`FormulaText`/`StudyFormulaText` 统一入口 |
| 自测先预选后提交 | 「提交答案」才算作答；进度按 learnedPageIndexes 计算 |
| AI 面板全局挂载 | AiCompanion 在 App.tsx 全局挂载（不在 ModuleView 内），经 activeStudyTaskId/activeStudySection 联动 |

## 不变量

- workspace 指纹（status/updatedAt/stage/modelUsage）变化才 refreshWorkspace；轮询 2s 常规、失败指数退避至 15s、连续 3 次失败置 offline
- 讲义数据结构 StudyGuide（sections/storyContext/workedExamples/selfTestQuestionIds/readabilityReview）为渲染契约
- 新功能放新组件文件；禁止在 ModuleView.tsx 新增顶层组件（CLAUDE.md 大文件守则）

## 禁区

- 不在 ModuleView.tsx 里继续堆功能（5910 行/104 useState 已超限，拆分走阶段3计划）
- 不用 demo 模式验收本域行为

## 设计异议

- docstring/类型行数有漂移（CLAUDE.md 记 103 useState，实测 104）；useState 热点：MaterialsView(~24)、StrategyReviewView(20)、PlanView+Dialog(16)、CourseOnboardingView(16)——待开发者裁决拆分优先级
