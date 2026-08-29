# modules/ 可见功能域总文档

本文件夹按**功能域**（前后端纵切）组织用户可见功能，一域一文件夹。
域地图（每个域对应的代码锚点与文档状态）见 [`../project.md` §3.1](../project.md)。

每个域文件夹内固定两件套：`design.md`（设计契约，人裁决）+ `designs-specs.md`（事实规格，AI 维护）——
这是 docs.md §2.4 登记的标准结构，代替单独的文件夹总文档。

**UI 挂载对照**（域 → 界面位置）：

| 界面位置 | 域 |
|---|---|
| 左侧边栏（菜单本体与切换） | sidebar-shell |
| 顶部导航栏 | topbar |
| 右侧面板容器 | right-panel |
| 侧边栏菜单项：总览/规划/复习主线/刷题/模拟卷/错题本/资料库/知识地图/专业名词/归档/设置 | overview / planning / mainline / practice / mock-exam / wrong-book / materials / mind-map / glossary / archive / settings |
| 学习页内：划词工具条/笔记/课程意见反馈/AI 伴学 | selection / notes / course-feedback / ai-companion |
| 复习计划（每日进度/时长/调整提案） | review-plan |
| 登录页 | auth-account |
