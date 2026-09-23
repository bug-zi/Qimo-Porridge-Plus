# 资料解析（material-parser）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| backend/app/material_parser.py | 811 | 抽取级联/转 PDF/XLSX 内置解析/解析缓存/AI 状态+预览 |
| backend/app/ocr_service.py | 278 | RapidOCR/PyMuPDF 封装、PDF 渲染、视觉兜底 |
| backend/app/materials.py | 414 | 扫描与同步编排、materialMemory digest |
| backend/app/paths.py | — | MATERIAL_CACHE_DIRECTORY = backend/data/material_cache |

## 调用链

上传 routers/materials.py:75 upload-batch → `upload_course_materials` → `materials.scan_course_materials:113` → `analyze_course_material`(material_parser:713) → `_extract_material_content`(:491)；预览 GET …/materials/preview → `build_material_preview`(:732)；转 PDF → `resolve_converted_material_pdf_path`(:333) → `_convert_file_to_pdf`(:272)；入库 `sync_course_knowledge:213` 命中解析缓存。

## 数据契约

- 缓存：`parse-{sha24}.json`（ANALYSIS_VERSION=5 失效机制）与 `preview-{sha24}.pdf`；无独立 DB 表，状态随 workspace materials 持久化
- 端点（routers/materials.py 全部 7 个）：preview/file/converted-file/upload-batch/role PATCH/delete/rescan

## 测试锚点

test_ocr_service.py（渲染识别/summarize_ocr_pages/弱页选择）、test_embedding_pdf_regressions.py:31-39（水印 PDF 过薄触发 OCR）、test_facade_exports.py:86-128（re-export 同一对象+禁环）、test_multi_tenant_isolation.py:34

## 上游调用方 / 下游消费方

- 依赖：模型调用（视觉 OCR `_model_completion`）、ocr_service、paths
- 下游：产出入 RAG检索 `sync_material_documents`；上传/删改触发 `mark_strategy_maintenance_pending` + maintain_review_plan/glossary_refresh 任务

## 导读

读序：`_extract_material_content`（级联主干）→ `_ocr_fallback_for_scanned_pdf`（扫描兜底）→ 缓存 key/version 机制。调解析问题先看缓存文件是否命中、ANALYSIS_VERSION 是否升过。
