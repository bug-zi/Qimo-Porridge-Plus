# 资料解析（material-parser）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

课程资料的文本抽取引擎：MarkItDown→Docling→RapidOCR→视觉模型兜底级联、Office 转 PDF、XLSX 内置解析、解析缓存与预览状态。产出文本供 RAG检索入库。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 级联硬编码本地优先 | 文本直读 → 图片 RapidOCR（<200 字/页升视觉，3 次重试）→ 通用 MarkItDown→Docling；无 soffice 显式失败，不静默降级 |
| PDF 密度校验 + 扫描件兜底 | 密度下限 max(200, 页数×40)，过薄走 RapidOCR 全文 → 最薄页（≤30 页上限）视觉重做，恒取较长结果 |
| 解析缓存 key=sha256(路径\|size\|mtime_ns)[:24] | ANALYSIS_VERSION=5 不符即失效；内置 PPTX 结果不落缓存 |
| xlsx 内置解析兜底 | MarkItDown 失败时 ZipFile+ElementTree 直读（前 3 表 60 行 16 列） |
| 路径安全硬校验 | `resolve_course_material_path` 拒反斜杠/冒号/../ 等危险路径 |

## 不变量

- aiStatus 阈值：>80 ready / 0-80 partial / 0 unreadable
- 禁模块级 import study_service（防成环）；函数体内延迟 import（study_service:201 re-export 保打桩面）
- OFFICE_TO_PDF_SUFFIXES 仅 {ppt,pptx,xls} 走 LibreOffice headless；`_find_soffice` env→PATH→3 个硬编码路径

## 禁区

- 不引入云端解析 API（本地优先原则）
- 不放松路径安全校验

## 设计异议

（无）
