# 归档（archive）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

课程与错题的软删除统一通道：归档 → 7 天保留 → 惰性+定时清理 → 永久删除/恢复。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 删除即软归档（archived_items 表，purge_after=deleted_at+7 天） | 防误删；课程与错题共用一条通道 |
| 课程归档 payload 双形态 | database 形态存 courses+planTasks 快照；workspace 形态存整个 workspace.json——恢复时不依赖磁盘文件仍在 |
| 恢复时补登记 courses 索引行 | 恢复后课程列表立即可见 |
| 惰性 purge（list/删除/恢复前）+ 60s 后台 loop 双保险 | 单一机制漏网时另一机制兜底 |
| 归属校验不通过统一 404 | 不泄露归档存在性 |

## 不变量

- ARCHIVE_RETENTION_DAYS=7；itemType ∈ 'course' | 'wrong-answer'
- 删课程同时清 15 张表 + data 目录 + embedding 缓存（permanently_delete_course_data）+ 前端 discardCourseNoteHighlights 清高亮锚点
- 前后端字段命名转换：ArchiveItemResponse(snake_case) → api.ts toArchiveItem(L170) 转驼峰

## 禁区

- 不许绕过归档直接物理删除（课程/错题删除入口必须走 create_archive_item）

## 设计异议

（无）
