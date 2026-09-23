# 侧边栏框架（sidebar-shell）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

左侧导航：11 个菜单项 + 当前课程上下文切换 + 视图切换。纯受控组件，不调 API。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 菜单 11 项固定（overview/materials/planning/mindmap/glossary/plan/practice/mock/errors/archive + settings） | 单列布局，宽度 92px（app-shell grid 第一列） |
| 激活态类名 `is-active` + `:root[data-theme]` 主题变量 | 与全局主题系统一致 |
| 'notes' 菜单项特殊转发右侧面板 | 笔记主入口在右栏（App.changeActiveModule L920 特判） |

## 不变量

- 纯受控：activeModule / onModuleChange 由 App 注入
- 课程上下文实际由 App.tsx 内联 CourseSwitcher(L246) 承担

## 禁区

- 不在 Sidebar 内发起 API 调用

## 设计异议

- **CoursePanel（Sidebar.tsx L118）全库无引用，是死代码**；课程切换真实入口是 App 内联 CourseSwitcher——待开发者裁决：删 CoursePanel 或把 CourseSwitcher 迁入本域
