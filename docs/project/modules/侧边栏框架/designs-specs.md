# 侧边栏框架（sidebar-shell）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| web/src/components/Sidebar.tsx | 277 | 导出 MainNavigation + CoursePanel（后者无引用，死代码） |
| web/src/components/OptionWheel.tsx | 358 | 垂直滚轮选择器（与顶部栏共用） |
| web/src/utils/courseTimeline.ts | 114 | 备考/历史课程分类排序纯函数 |

## 结构链

App.tsx L1919 `<MainNavigation activeModule onModuleChange>` 渲染于 app-shell 左列（grid-row:1/-1）；onModuleChange=changeActiveModule（L920，'notes' 特殊转发右侧面板）。

## 数据契约

纯受控无 API；types.ts:LearningModule(L1)、Course(L195)。

## 测试锚点

无（前端仅 courseFeedbackState.test.ts）。

## 上游调用方 / 下游消费方

归档菜单项 → 归档域；notes 项 → 右侧面板框架；OptionWheel 与顶部栏共用。

## 导读

三个小文件；改菜单先对齐 App.tsx 的 activeModule 分发（ModuleView L5785-5833）。
