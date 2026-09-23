# 笔记（notes）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

划词添加到笔记、正文高亮持久化、笔记面板/笔记页。笔记本体是 workspace 的 Markdown 字段，高亮是 CSS Custom Highlight API + localStorage 文本锚点的纯前端层。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 不用 `<mark>` 改 DOM，用 Custom Highlight API（不支持时静默降级） | 避免与 React 受控内容冲突 |
| Range 不可序列化 → 存 .app-shell 拍平文本流偏移 + 前后 32 字符锚（Web Annotation TextQuoteSelector 思路） | 跨会话恢复高亮；定位时校验原文一致才直中 |
| 索引只统计"可高光正文"节点（排除右栏/笔记页/工具栏/输入控件） | 防止恢复时命中笔记面板自己的引用块 |
| 兜底恢复源：笔记引用块（> 引用块）反推 | localStorage 丢失仍可重建高亮 |
| 删除笔记时同内容多摘录只删最早一条 | 与高光逐条移除顺序一致 |
| 删除课程时 discardCourseNoteHighlights 清孤儿 | 防 localStorage 无限膨胀 |

## 不变量

- workspace `note: string`（Markdown，摘录以 > 引用块内嵌）；note 非 None 才覆盖（update_workspace_state）
- localStorage 键 `final-congee-note-highlights:<courseId>`
- 550ms 防抖 PUT + beforeunload keepalive flush
- pending 高亮 MutationObserver + 200ms 防抖重试，上限 25 次（≈5s），导航重置计数

## 禁区

- 高亮锚点格式变更必须写迁移（localStorage 已有存量）

## 设计异议

- 无专门测试（note 仅经 workspace PUT 隐式覆盖）——三级定位/锚点恢复逻辑复杂度不低，待开发者裁决是否补测
