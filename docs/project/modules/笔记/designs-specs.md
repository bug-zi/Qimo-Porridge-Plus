# 笔记（notes）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| web/src/utils/noteHighlights.ts | 504 | CSS Custom Highlight API 持久高光 + localStorage 文本锚点（buildTextIndex 三级定位：偏移直中→前后锚搜索→裸摘录） |
| web/src/components/NoteHighlightDismiss.tsx | 109 | 点击高光弹"移出笔记"确认浮条（caretPositionFromPoint→isPointInRange 反查） |
| web/src/components/NotesSidebarPanel.tsx | 54 | 右侧面板笔记（Markdown 预览/编辑） |
| web/src/components/ModuleView.tsx | — | NotesView(L4186，独立笔记页，同构) |
| web/src/App.tsx | — | updateNote(L1057，550ms 防抖)、appendNoteSnippet(L1074)、removeNoteSnippet(L1141，按归一化文本删最早引用块)、restoreNoteHighlights(L796)、beforeunload flush(L625) |
| backend（workspace 域承载） | — | note 字段；PUT /api/courses/{id}/workspace → update_workspace_state（review_plan.py:518，note 非 None 才覆盖）；初始模板 workspace.py:243 |

## 调用链

SelectionToNoteToolbar.onAddToNote → appendNoteSnippet → updateNote →（防抖）→ updateCourseWorkspace。恢复：App useEffect [activeCourseId, activeModule, note] → restoreNoteHighlights → buildTextIndex 三级定位 → pending 由 MutationObserver 重试。删除：NoteHighlightDismiss → removeNoteHighlight + removeNoteSnippet 同步删引用块。

## 数据契约

- workspace note: string（Markdown）；localStorage `final-congee-note-highlights:<courseId>`：NoteHighlightRecord{id,snippet(归一化),domText,start,end,prefix,suffix(32字符),derivedFromNote?}
- API：PUT /courses/{id}/workspace{note?}；CSS `::highlight(note-snippet)`

## 测试锚点

无专门测试（note 经 workspace PUT 隐式覆盖）；前端无。

## 上游调用方 / 下游消费方

- 依赖：划词基础（入口）、专业名词（笔记预览 Markdown 经 glossaryMarkdownComponents 包裹）、存储与工作区（note 随 StudyWorkspace 读写）、课程意见反馈（.course-feedback-backdrop 在排除表）

## 导读

读序：noteHighlights.ts 的 buildTextIndex 与恢复逻辑（全域最复杂）→ App.tsx 的四个 handler → NotesSidebarPanel。
