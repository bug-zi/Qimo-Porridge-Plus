# 划词基础（selection）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| web/src/hooks/useTextSelection.ts | 93 | 全局选区监听，输出标准化快照 |
| web/src/components/SelectionToNoteToolbar.tsx | 215 | 浮动工具栏（添加到笔记 + 课程意见反馈）+ 反馈对话框 |
| web/src/App.tsx | — | L2194-2202 单例挂载（onAddToNote=appendNoteSnippet + 6 个反馈回调） |

## 调用链

document mouseup/keyup → `readSelection`(L20) → TextSelectionSnapshot → SelectionToNoteToolbar（createPortal 挂 body）→ handleAdd(L167) → `highlightSnippetSelection`（笔记域）+ onAddToNote；反馈分支 `feedbackContextFromSelection`(L79) 采集上下文 → feedbackDialogReducer 状态机（课程意见反馈域）。

## 数据契约

- TextSelectionSnapshot{text,rect}；CourseFeedbackDraft{selectedText,userComment,context}；CourseFeedbackContext{beforeText,afterText,sectionText,route,taskId,…,selectionFragments?}（types.ts）
- DOM 锚点约定：`[data-course-feedback-scope/field]`、`[data-story-section]`

## 测试锚点

无（纯前端，前后端均无对应测试）。

## 上游调用方 / 下游消费方

- 下游：笔记域（highlightSnippetSelection / appendNoteSnippet）、课程意见反馈域（reducer/Preview/路由）、专业名词域（.glossary-term 在排除表）

## 导读

两个文件即全部；改交互先看 useTextSelection 的事件过滤条件再动工具栏。
