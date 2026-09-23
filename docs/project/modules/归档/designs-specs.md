# 归档（archive）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| backend/app/routers/deps.py | 282 | ARCHIVE_RETENTION_DAYS=7(L22)、create_archive_item(L238)、list_active_archive_items(L210)、permanently_delete_archive_item(L185)、purge_expired_archive_items(L200)、permanently_delete_course_data(L113) |
| backend/app/main.py | — | L146-157 建表；L223-233 每 60s purge loop；lifespan 启动即清 |
| backend/app/routers/courses.py | — | L546 DELETE 课程→归档；L642-776 archive 列表/永久删除/恢复 |
| web/src/App.tsx | — | archiveItems state(L506)、删除确认框(L1722/L1688)、恢复/永久删除 handlers(L1027/L1016) |
| web/src/components/ModuleView.tsx | — | ArchiveView(L4497-4625) |

## 调用链

侧边栏 'archive' → ModuleView L5852 → ArchiveView（恢复/永久删除）；课程删除入口=CourseSwitcher→handleDeleteCourse→confirmDeleteCourse→deleteCourse；错题删除=ErrorsView→deleteCourseWrongAnswer。

## 数据契约

- archived_items 表（payload JSON、purge_after）；API：GET /api/archive、DELETE /api/archive/{id}、POST /api/archive/{id}/restore、DELETE /api/courses/{id}、DELETE /api/courses/{id}/wrong-answers/{wid}
- TS：ArchiveItem（types.ts:473）↔ ArchiveItemResponse（deps.py:65，snake_case→toArchiveItem 转驼峰）

## 测试锚点

test_archive_purge.py（2 用例：手动永久删除清库+课程目录；过期 purge 清真实数据而非只删行）

## 上游调用方 / 下游消费方

- 依赖：存储与工作区（load/save）、错题本（错题归档）、复习计划（plan_tasks 表）、认证与隔离（owner_id）、笔记（前端高亮锚点清理）
- 外部MCP 的 external_sources 行也被归档覆盖（deps.py:152）

## 导读

读序：deps.py 的 6 个归档函数 → test_archive_purge（行为契约）→ ArchiveView。改删除链路必须同时检查 permanently_delete_course_data 的 15 张表清单是否与建表处同步。
