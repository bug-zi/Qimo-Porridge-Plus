# 右侧面板框架（right-panel）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

右侧第三列面板容器：AI伴学（chat/agent）与笔记双面板切换、宽度拖拽、折叠态、策略审核接管槽。容器状态全部在 App.tsx。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 容器状态在 App（activeRightPanel/isAiOpen/isAiCollapsed/aiPanelWidth） | AiCompanion 保持展示组件属性 |
| 面板宽度经 `--ai-panel-width` CSS 变量注入 app-shell 内联 style | 三列 grid（92px / 1fr / ai-panel）单点控制 |
| 策略审核接管槽（#strategy-revision-slot） | 策略生成时接管右栏（规划域联动） |
| 流式消息独立 memo | SSE 打字机不重渲整面板 |
| 折叠态双按钮 rail + 类名 `ai-panel is-{panel}-panel is-collapsed` | 窄屏 ≤1180px 自动停靠 |

## 不变量

- AiCompanion 不直连 API（数据经 props；笔记持久化走 App 的 550ms 防抖 PUT + beforeunload flush）
- 拖拽范围 280–620px

## 禁区

- 面板内不新增第三种面板类型时不要扩展 activeRightPanel 联合类型之外的切换逻辑

## 设计异议

（无）
