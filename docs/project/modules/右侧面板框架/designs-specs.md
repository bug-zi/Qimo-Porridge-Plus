# 右侧面板框架（right-panel）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| web/src/components/AiCompanion.tsx | 770 | aside.ai-panel 容器（AI chat/agent + 笔记双面板，详见 AI伴学域） |
| web/src/components/NotesSidebarPanel.tsx | 54 | Markdown 笔记预览/编辑切换（详见笔记域） |
| web/src/App.tsx | — | activeRightPanel(L546)、isAiOpen/isCollapsed/aiPanelWidth(L150-152)、openRightPanel(L914)、拖拽 handleAiPanelResizeStart(L875)、内联 style(L814) |

## 结构链

App.tsx L2090 `<AiCompanion>` 第三列；activePanel==='notes' 时 L761 渲染 `<NotesSidebarPanel note onNoteChange>`（note=activeWorkspace.note，onNoteChange=updateNote）。

## 数据契约

不直连 API；props 消费 StudyWorkspace.note/messages、AdjustmentProposal（types.ts:507）、StreamingMessage(L502)、GlobalCourseFeedbackResult；笔记持久化 PUT /api/courses/{id}/workspace（api.ts:711 / flushCourseWorkspaceNote L731）。

## 测试锚点

无。

## 上游调用方 / 下游消费方

- 下游注入：专业名词（glossaryMarkdownComponents 渲染全部 Markdown）、划词基础/笔记（appendNoteSnippet）、课程意见反馈（反馈预览）、规划（strategyReviewActive 接管）

## 导读

容器逻辑集中在 App.tsx L150-152/L546/L814-914；面板内容分属 AI伴学与笔记两域文档。
