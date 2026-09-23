# 复习主线（mainline）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单（web/src/）

| 文件 | 行数 | 职责 |
|---|---|---|
| components/ModuleView.tsx | 5910 | 学习页全部子视图（见结构链）；CLAUDE.md 大文件守则对象 |
| components/CourseGenerationStatusCard.tsx | 70 | 生成任务状态卡（仅 PlanView 内使用） |
| components/CourseMindMapView.tsx | 1715 | 知识地图（lazy 加载，详见知识地图域） |
| components/CoursePreferencesPanel.tsx | 51 | 课程偏好面板 |
| components/CourseFeedbackPreview.tsx | 26 | 反馈预览 |
| hooks/useStrategyGenerationJob.ts | 162 | 生成任务轮询（2s/退避 15s/offline 判定/指纹刷新） |
| features/courseGeneration/generationStatus.ts | — | 错误分类/心跳健康 |
| services/courseFeedbackLifecycleApi.ts | — | 反馈生命周期 API 封装 |

## 结构链

App.tsx:2009 挂载 `<ModuleView>`（~30 props：course/tasks/knowledgePoints/practiceQuestions/mockQuestions/onboarding/strategyDocuments/readabilityReview + onXxx 回调）。ModuleView（5728-5910）为分发器：`activeStudyTask` 命中 → OrientationTaskView（2603，导引六页）或 StudyTaskView（2868，讲义主体：速成讲解+公式+自测先选后提交+练习关联题）；否则按 activeModule 分发 CourseOnboardingView(1234，含诊断) / StrategyReviewView(1613) / DiagnosticResultView(2054) / OverviewView(444) / PlanView(996，生成状态卡) / PracticeView(3513) / MockView(3903) / Notes/Errors/Archive/Materials/GlossaryView。AiCompanion 由 App.tsx:2090 全局挂载。

## 数据契约

- `GET /courses/{id}/workspace` → StudyWorkspace（types.ts:794）；`PlanTask.studyGuide?: StudyGuide`（types.ts:454/354）
- 轮询：getActiveStrategyGenerationJob / getAgentJob / cancelAgentJob；恢复用 getActiveStrategyGenerationJob；App 侧 refreshGenerationWorkspace（App.tsx:762）字段级合并保留本地态
- 其他：saveCourseSetup、submitCourseDiagnostic、strategy 读写/审批、submitCoursePracticeAnswer（返回 correct/explanation/mastery/generatedSimilarCount）、/mind-map 系列
- 字体：UiFont 10 种（types.ts:26）+ 6 档字号，正文 ReadableStudyText

## 测试锚点

前端仅 1 个测试：components/courseFeedbackState.test.ts（反馈 reducer）。讲义渲染/轮询/自测 0 测试（阶段3 待补）。

## 上游调用方 / 下游消费方

- 上游：课程生成流水线（workspace 内容）、规划域（策略审核入口）、后台队列（job 状态轮询）
- 下游宿主：划词基础/笔记/课程意见反馈/AI伴学 在学习页内激活

## 导读

读序：ModuleView 顶层分发器（5728-5910）→ StudyTaskView（2868）→ useStrategyGenerationJob。**不要全文通读 ModuleView**；改哪区读哪区（useState 热点分区见 design.md 异议节）。改动前后必跑验证三件套。
