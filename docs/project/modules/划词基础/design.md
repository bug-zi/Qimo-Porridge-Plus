# 划词基础（selection）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

划词交互基础设施：全局选区监听 + 浮动工具栏（添加到笔记 / 课程意见反馈），并为反馈采集结构化 DOM 上下文锚点。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 选区必须落在 .app-shell 内，排除 input/textarea/select/contenteditable | 避免表单内选词误触发 |
| mouseup/keyup 才捕获；selectionchange 仅在清空时隐藏；scroll/resize 用 rAF 重定位 | 防拖拽抖动与性能损耗 |
| 工具栏 portal 挂 body，定位钳制 EDGE_PADDING=150 | 绕开 .app-shell zoom 与溢出裁剪 |
| 「添加到笔记」onMouseDown preventDefault | 防点击导致选区丢失 |
| 反馈 fragment 按 TreeWalker 精确切片，跨 task 选区丢弃 fragments | Firefox 多 range 场景的精确采集 |

## 不变量

- 快照契约 `TextSelectionSnapshot{text, rect}`；折叠光标（rect 宽高全 0）忽略
- 反馈上下文：beforeText/afterText 各 900 字符、sectionText ≤6000、`data-course-feedback-*` 字段片段
- 挂载时恢复上次未确认的 rewriteProposal

## 禁区

- 工具栏不直连 API（只回调 App handlers）

## 设计异议

- 纯前端域，前后端均无测试——待开发者裁决是否为 hook 补 vitest
