# 存储与工作区（storage）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

数据落盘的地基：SQLite 多域表、workspace.json 整文件读写（per-course 文件锁 + 乐观锁）、路径常量唯一定义点、双存储分工、课程归档与彻底删除。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| paths.py 零依赖 + 属性访问 | 防 sys.modules 副本导致测试 patch 失效、防误写真实库（L5-10 约定） |
| workspace/拆分模块禁模块级 import study_service | 防循环导入；缝合点函数内延迟 import 保住 monkeypatch 打桩面（模块头 L7-12） |
| 保存三件套：expected_revision 乐观锁 + revision 单调 +1 + tasks 变了才递增 planRevision | 并发写安全；前端可据此检测冲突（"已被其他操作更新"） |
| 原子写 `.name.pid.tmp` + os.replace | 断电/崩溃不留半文件 |
| load 即迁移 | 内容质量守卫（WORKSPACE_CONTENT_VERSION=4、4 段 sections 规范化、悬空 knowledgePointId 修复）、未作答单选重洗一次性迁移（已作答/错题保持原样防索引错位） |
| 双存储分工 | SQLite=元数据/队列/术语/知识库/chat；workspace.json=课程全部学习内容（整文件读写）；mind_map.json=布局；strategy/*.md=计划全文 |
| 归档 7 天保留 + 60s 后台清理 loop | purge_after 机制 |

## 不变量

- course_id 硬校验 `^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$`
- per-course RLock 两个：`_workspace_lock`（读写）与 `_content_generation_lock`（背景生成等锁 30min、交互 fast-fail）
- 非 planned 状态 `_clear_pre_plan_content` 清空预置内容
- 多租户：仅 courses/archived_items 带 owner_id，其余表靠 course_id 传递隔离

## 禁区

- 任何测试/脚本不得清库（backend/data/exam_booster.db 是真实学习数据，CLAUDE.md 数据安全）
- 停后端才能整体备份 backend/data/（运行时有 -wal/-shm）

## 设计异议

（无）
