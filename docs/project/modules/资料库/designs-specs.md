# 资料库（materials）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| backend/app/materials.py | 414 | 扫描/角色/资料记忆/上传/同步编排（upload_course_materials:270、scan_course_materials:89、_mark_material_memory:172、sync_course_knowledge:195、refresh_workspace_materials:380、_apply_material_roles:69） |
| backend/app/routers/materials.py | 169 | 7 端点（main.py:300 注册） |
| backend/app/study_service.py | — | :195-270 门面 re-export（打桩 patch 本体） |
| web/src/api.ts | — | :440-496 preview/file/converted-file URL + rescan/upload/role/delete |
| web/src/components/ModuleView.tsx | — | MaterialsView(:4745，挂载 :5855) |
| web/src/App.tsx | — | handlers :1482-1512 |

## 调用链

upload-batch(:75) → `upload_course_materials` → 落盘+materialRoles 登记 → scan → _mark_material_memory → sync_course_knowledge → save_workspace → mark_strategy_maintenance_pending → 入队 maintain/glossary job。role PATCH(:114)/delete(:141)/rescan(:157) 同下游。sync 链：_apply_material_roles → 逐资料 _extract_material_content → sync_material_documents → import_workspace_messages → get_knowledge_status → 写 workspace.knowledgeBase。

## 数据契约

- 磁盘：data/courses/<id>/materials/ 递归
- workspace：materials[]（role/isPrimary/priorityOrder/analysisVersion/aiStatus/previewStatus/excerpt…）、materialRoles{path:{role,priorityOrder}}、materialMemory、materialAnalysisRefreshedAt、knowledgeBase
- 端点：GET materials/preview\|file\|converted-file/{path}；POST upload-batch?role=；PATCH materials/{path}/role；DELETE materials/{path}；POST materials/rescan
- TS：Material(:531)、MaterialMemory(:572)、StudyWorkspace.materialMemory/knowledgeBase(:811/812)

## 测试锚点

test_facade_exports.py:130-156（门面同一性）、:318；test_mainline_generation_repair.py:258-259（scan/sync 打桩示范）；upload 链被 8+ 测试经 caller 覆盖。

## 上游调用方 / 下游消费方

- 下游：RAG检索（解析入库与检索）、资料解析（analyze/preview/转PDF）、复习计划与专业名词（变更触发 job）、外部MCP（导入落库 upload_course_material）、知识地图（经 workspace 间接消费）
- 启动时 main.py:249-256 逐课程 sync（单课失败不阻断）

## 导读

读序：materials.py 的 upload/scan/sync 三主函数 → digest 失效机制 → routers/materials.py。注意打桩面：测试须 patch materials.py 本体而非 study_service 门面。
