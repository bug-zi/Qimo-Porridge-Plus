"""资料解析域（阶段2-2 从 study_service.py 抽取）。

职责：单文件的文本抽取（MarkItDown/Docling/RapidOCR/视觉模型级联）、
Office 转 PDF 预览、XLSX 内置解析、解析缓存、AI/预览状态标注。

依赖方向：material_parser → model_client / ocr_service / paths，
禁止模块级 import study_service（study_service 会 import 本模块，会成环）。
`_course_material_directory` 属于 workspace 路径域（留在 study_service），
本模块在函数体内延迟 import——调用时读取 study_service 命名空间，
测试 patch study_service._course_material_directory 依旧生效。

测试注意：要打桩解析器（_extract_with_markitdown / _ocr_fallback_for_scanned_pdf 等）
请 patch 本模块，study_service 上的名字只是 re-export 别名。
"""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree
from zipfile import ZipFile

from . import ocr_service
from . import paths
from .model_client import _model_completion

SPREADSHEET_NAMESPACE = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
SPREADSHEET_RELATIONSHIP_NAMESPACE = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PACKAGE_RELATIONSHIP_NAMESPACE = "{http://schemas.openxmlformats.org/package/2006/relationships}"
XLSX_PREVIEW_MAX_ROWS = 60
XLSX_PREVIEW_MAX_COLUMNS = 16
MATERIAL_ANALYSIS_VERSION = 5
TEXT_SUFFIXES = {"md", "txt"}
IMAGE_SUFFIXES = {"jpg", "jpeg", "png", "gif", "webp"}
MARKITDOWN_SUFFIXES = {"pdf", "pptx", "xlsx", "xls", "docx", "doc", "csv", "md", "txt"}
DOCLING_SUFFIXES = {"pdf", "pptx", "xlsx", "docx", "doc", "csv", "png", "jpg", "jpeg", "webp"}
OFFICE_TO_PDF_SUFFIXES = {"ppt", "pptx", "xls"}

_MARKITDOWN_CONVERTER: Any | None = None
_MARKITDOWN_ERROR = ""
_DOCLING_CONVERTER: Any | None = None
_DOCLING_ERROR = ""


def _extract_pptx_excerpt(file_path: Path) -> tuple[int, str]:
    namespace = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    try:
        with ZipFile(file_path) as archive:
            slide_names = sorted(
                name
                for name in archive.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            )
            snippets: list[str] = []
            for slide_name in slide_names[:14]:
                root = ElementTree.fromstring(archive.read(slide_name))
                text = " ".join(
                    node.text.strip()
                    for node in root.findall(".//a:t", namespace)
                    if node.text and node.text.strip()
                )
                if text:
                    snippets.append(text)
        return len(slide_names), "；".join(snippets)[:1600]
    except Exception:
        return 0, ""


def resolve_course_material_path(relative_path: str, course_id: str) -> Path:
    from .study_service import _course_material_directory

    if "\\" in relative_path or ":" in relative_path:
        raise FileNotFoundError("资料路径无效")

    material_path = PurePosixPath(relative_path)
    if material_path.is_absolute() or any(part in {"", ".", ".."} for part in material_path.parts):
        raise FileNotFoundError("资料路径无效")

    course_directory = _course_material_directory(course_id).resolve()
    file_path = course_directory.joinpath(*material_path.parts).resolve()
    if course_directory not in file_path.parents or not file_path.is_file() or file_path.name == "AGENTS.md":
        raise FileNotFoundError("未找到资料文件")
    return file_path


def _read_xlsx_shared_strings(archive: ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []

    strings: list[str] = []
    for item in root.findall(f"{SPREADSHEET_NAMESPACE}si"):
        strings.append("".join(node.text or "" for node in item.findall(f".//{SPREADSHEET_NAMESPACE}t")))
    return strings


def _read_xlsx_sheet_paths(archive: ZipFile) -> list[tuple[str, str]]:
    workbook_root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    relationships_root = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relationships = {
        item.attrib["Id"]: item.attrib["Target"]
        for item in relationships_root.findall(f"{PACKAGE_RELATIONSHIP_NAMESPACE}Relationship")
        if item.attrib.get("Id") and item.attrib.get("Target")
    }

    sheets: list[tuple[str, str]] = []
    for sheet in workbook_root.findall(f".//{SPREADSHEET_NAMESPACE}sheet"):
        sheet_id = sheet.attrib.get(f"{SPREADSHEET_RELATIONSHIP_NAMESPACE}id")
        target = relationships.get(sheet_id or "")
        if not target:
            continue
        sheet_path = target.lstrip("/")
        if not sheet_path.startswith("xl/"):
            sheet_path = f"xl/{sheet_path}"
        sheets.append((sheet.attrib.get("name", "工作表"), sheet_path))
    return sheets


def _xlsx_column_index(cell_reference: str) -> int:
    match = re.match(r"([A-Z]+)", cell_reference.upper())
    if not match:
        return 0

    column = 0
    for char in match.group(1):
        column = column * 26 + ord(char) - ord("A") + 1
    return column


def _read_xlsx_cell(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(f".//{SPREADSHEET_NAMESPACE}t")).strip()

    value_node = cell.find(f"{SPREADSHEET_NAMESPACE}v")
    raw_value = value_node.text if value_node is not None and value_node.text is not None else ""
    if not raw_value:
        formula = cell.find(f"{SPREADSHEET_NAMESPACE}f")
        return f"={formula.text}" if formula is not None and formula.text else ""

    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)]
        except (IndexError, ValueError):
            return raw_value
    if cell_type == "b":
        return "TRUE" if raw_value == "1" else "FALSE"
    return raw_value


def _extract_xlsx_preview(file_path: Path) -> list[dict[str, Any]]:
    with ZipFile(file_path) as archive:
        shared_strings = _read_xlsx_shared_strings(archive)
        sheet_paths = _read_xlsx_sheet_paths(archive)
        preview_sheets: list[dict[str, Any]] = []
        for sheet_name, sheet_path in sheet_paths[:3]:
            root = ElementTree.fromstring(archive.read(sheet_path))
            rows: list[list[str]] = []
            max_used_column = 0
            for row in root.findall(f".//{SPREADSHEET_NAMESPACE}sheetData/{SPREADSHEET_NAMESPACE}row"):
                if len(rows) >= XLSX_PREVIEW_MAX_ROWS:
                    break
                row_values = [""] * XLSX_PREVIEW_MAX_COLUMNS
                for cell in row.findall(f"{SPREADSHEET_NAMESPACE}c"):
                    column = _xlsx_column_index(cell.attrib.get("r", ""))
                    if column < 1 or column > XLSX_PREVIEW_MAX_COLUMNS:
                        continue
                    value = _read_xlsx_cell(cell, shared_strings)
                    row_values[column - 1] = value
                    if value:
                        max_used_column = max(max_used_column, column)
                if any(row_values):
                    rows.append(row_values)
            if rows:
                preview_sheets.append(
                    {
                        "name": sheet_name,
                        "rows": [row[:max_used_column] for row in rows],
                    }
                )
        return preview_sheets


def _relative_material_path(file_path: Path, course_id: str) -> str:
    from .study_service import _course_material_directory

    return str(file_path.relative_to(_course_material_directory(course_id))).replace("\\", "/")


def _material_cache_key(file_path: Path) -> str:
    stat = file_path.stat()
    raw_key = f"{file_path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:24]


def _material_cache_path(file_path: Path, kind: str, suffix: str) -> Path:
    return paths.MATERIAL_CACHE_DIRECTORY / f"{kind}-{_material_cache_key(file_path)}.{suffix}"


def _normalize_extracted_text(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    compact_lines: list[str] = []
    blank_seen = False
    for line in lines:
        if not line.strip():
            if not blank_seen:
                compact_lines.append("")
            blank_seen = True
            continue
        compact_lines.append(line)
        blank_seen = False
    return "\n".join(compact_lines).strip()


def _load_cached_parse(file_path: Path) -> dict[str, Any] | None:
    cache_path = _material_cache_path(file_path, "parse", "json")
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("analysisVersion") != MATERIAL_ANALYSIS_VERSION:
        return None
    text = data.get("text")
    return data if isinstance(text, str) and text.strip() else None


def _save_cached_parse(file_path: Path, parsed: dict[str, Any]) -> None:
    if not parsed.get("text"):
        return
    if str(parsed.get("parser", "")).startswith("内置 PPTX"):
        return
    paths.MATERIAL_CACHE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    cache_path = _material_cache_path(file_path, "parse", "json")
    cache_path.write_text(
        json.dumps({**parsed, "analysisVersion": MATERIAL_ANALYSIS_VERSION}, ensure_ascii=False),
        encoding="utf-8",
    )


def _find_soffice() -> str:
    configured_path = os.getenv("EXAM_BOOSTER_SOFFICE_PATH", "").strip()
    if configured_path and Path(configured_path).is_file():
        return configured_path

    for command_name in ("soffice", "libreoffice"):
        command_path = shutil.which(command_name)
        if command_path:
            return command_path

    for candidate in (
        Path("D:/app/工具箱/LibreOffice-文件格式转换/program/soffice.exe"),
        Path("C:/Program Files/LibreOffice/program/soffice.exe"),
        Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    return ""


def _convert_file_to_pdf(file_path: Path) -> dict[str, Any]:
    suffix = file_path.suffix.lower().lstrip(".")
    if suffix not in OFFICE_TO_PDF_SUFFIXES:
        return {"available": False, "reason": "该格式不需要转换为 PDF 预览。"}

    cache_path = _material_cache_path(file_path, "preview", "pdf")
    if cache_path.exists():
        return {
            "available": True,
            "path": str(cache_path),
            "tool": "LibreOffice",
            "message": "已生成 PDF 预览缓存。",
        }

    soffice_path = _find_soffice()
    if not soffice_path:
        return {
            "available": False,
            "reason": "未检测到 LibreOffice/soffice，暂不能把该格式自动转换为 PDF。",
        }

    paths.MATERIAL_CACHE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="material-convert-", dir=paths.MATERIAL_CACHE_DIRECTORY) as temp_dir:
        temp_path = Path(temp_dir)
        try:
            result = subprocess.run(
                [
                    soffice_path,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(temp_path),
                    str(file_path),
                ],
                capture_output=True,
                cwd=temp_path,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return {"available": False, "reason": f"PDF 转换失败：{error}"}

        converted_path = temp_path / f"{file_path.stem}.pdf"
        if not converted_path.exists():
            converted_files = list(temp_path.glob("*.pdf"))
            converted_path = converted_files[0] if converted_files else converted_path
        if result.returncode != 0 or not converted_path.exists():
            detail = (result.stderr or result.stdout or "转换器未输出 PDF").strip()
            return {"available": False, "reason": f"PDF 转换失败：{detail[:300]}"}

        converted_path.replace(cache_path)
        return {
            "available": True,
            "path": str(cache_path),
            "tool": "LibreOffice",
            "message": "已转换为 PDF，可在浏览器中预览。",
        }


def resolve_converted_material_pdf_path(relative_path: str, course_id: str) -> Path:
    file_path = resolve_course_material_path(relative_path, course_id)
    conversion = _convert_file_to_pdf(file_path)
    if not conversion.get("available") or not conversion.get("path"):
        raise FileNotFoundError(conversion.get("reason", "未生成 PDF 预览"))
    return Path(str(conversion["path"]))


def _get_markitdown_converter() -> tuple[Any | None, str]:
    global _MARKITDOWN_CONVERTER, _MARKITDOWN_ERROR
    if _MARKITDOWN_CONVERTER is not None:
        return _MARKITDOWN_CONVERTER, ""
    if _MARKITDOWN_ERROR:
        return None, _MARKITDOWN_ERROR
    try:
        from markitdown import MarkItDown

        _MARKITDOWN_CONVERTER = MarkItDown()
        return _MARKITDOWN_CONVERTER, ""
    except Exception as error:
        _MARKITDOWN_ERROR = f"MarkItDown 未安装或不可用：{error}"
        return None, _MARKITDOWN_ERROR


def _extract_with_markitdown(file_path: Path) -> tuple[str, str]:
    converter, error = _get_markitdown_converter()
    if converter is None:
        return "", error
    try:
        result = converter.convert(str(file_path))
        return _normalize_extracted_text(getattr(result, "text_content", "")), ""
    except Exception as error:
        return "", f"MarkItDown 解析失败：{error}"


def _get_docling_converter() -> tuple[Any | None, str]:
    global _DOCLING_CONVERTER, _DOCLING_ERROR
    if _DOCLING_CONVERTER is not None:
        return _DOCLING_CONVERTER, ""
    if _DOCLING_ERROR:
        return None, _DOCLING_ERROR
    try:
        from docling.document_converter import DocumentConverter

        _DOCLING_CONVERTER = DocumentConverter()
        return _DOCLING_CONVERTER, ""
    except Exception as error:
        _DOCLING_ERROR = f"Docling 未安装或不可用：{error}"
        return None, _DOCLING_ERROR


def _extract_with_docling(file_path: Path) -> tuple[str, str]:
    converter, error = _get_docling_converter()
    if converter is None:
        return "", error
    try:
        result = converter.convert(str(file_path))
        return _normalize_extracted_text(result.document.export_to_markdown()), ""
    except Exception as error:
        return "", f"Docling 解析失败：{error}"


def _extract_image_with_vision(file_path: Path) -> tuple[str, str]:
    mime_type = mimetypes.guess_type(file_path.name)[0] or "image/png"
    image_data = base64.b64encode(file_path.read_bytes()).decode("ascii")
    prompt = """
你是课程资料视觉 OCR 解析器。请完整读取图片，并把内容整理成可检索的 Markdown 文本。
规则：
1. 尽量逐字保留标题、正文、题目、选项、表格、公式、数字、单位、页码和手写批注。
2. 保留原有层级与题目顺序；表格使用 Markdown 表格，公式使用普通可读文本。
3. 图表或流程图除转写文字外，补充其坐标、箭头、结构和关键关系。
4. 只记录图片中可见或可可靠判断的内容；不要代替用户解题，不要补写图片中没有的答案。
5. 不要输出“OCR结果”等无关开场，直接输出资料正文。
"""
    messages = [
        {"role": "system", "content": prompt.strip()},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"请解析课程资料图片：{file_path.name}"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_data}"},
                },
            ],
        },
    ]
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            text = _model_completion(messages)
            return _normalize_extracted_text(text), ""
        except Exception as error:
            last_error = error
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    return "", f"AI 视觉 OCR 失败：{last_error}"


def _sheets_to_markdown(sheets: list[dict[str, Any]]) -> str:
    sections: list[str] = []
    for sheet in sheets:
        rows = sheet.get("rows", [])
        if not rows:
            continue
        sections.append(f"### {sheet.get('name', '工作表')}")
        for row in rows:
            sections.append(" | ".join(str(cell).strip() for cell in row))
    return _normalize_extracted_text("\n".join(sections))


def _ocr_fallback_for_scanned_pdf(file_path: Path) -> tuple[str, str, list[str]]:
    """扫描版 PDF 的 OCR 级联：RapidOCR 全文快筛 → 薄弱页视觉模型兜底。

    返回 (text, parser, errors)。RapidOCR 逐页识别后，平均每页字符数
    低于阈值的文件视为版面复杂/手写，把识别量最少的页面（至多
    VISION_FALLBACK_MAX_PAGES 页）交给视觉模型重做，取两者较优结果。
    """
    errors: list[str] = []
    rapid_text, rapid_error = ocr_service.extract_scanned_pdf_with_rapidocr(file_path)
    normalized = _normalize_extracted_text(rapid_text)
    if not normalized:
        if rapid_error:
            errors.append(rapid_error)
        return "", "", errors

    page_count, avg_chars = ocr_service.summarize_ocr_pages(normalized)
    if avg_chars >= ocr_service.OCR_MIN_CHARS_PER_PAGE:
        return normalized, f"RapidOCR 本地 OCR（{page_count} 页）", errors

    # RapidOCR 结果偏薄：挑识别量最少的页面升级视觉模型。
    if rapid_error:
        errors.append(rapid_error)
    page_sizes: list[tuple[int, int]] = []
    for index, section in enumerate(normalized.split("<!-- 第 ")[1:], start=1):
        body = section.split("-->", 1)[-1] if "-->" in section else section
        page_sizes.append((len(body.replace("\n", "").strip()), index))
    weak_pages = [number for _, number in sorted(page_sizes)[: ocr_service.VISION_FALLBACK_MAX_PAGES]]
    vision_text, vision_error = ocr_service.extract_pdf_pages_for_vision(
        file_path,
        weak_pages,
        lambda messages: _model_completion(messages),  # type: ignore[arg-type]
    )
    vision_normalized = _normalize_extracted_text(vision_text)
    if len(vision_normalized) > len(normalized):
        return vision_normalized, f"AI 视觉 OCR（扫描 PDF {len(weak_pages)} 页兜底）", errors
    if vision_error:
        errors.append(vision_error)
    return normalized, f"RapidOCR 本地 OCR（{page_count} 页，部分页识别较薄）", errors


def _extract_native_xlsx(file_path: Path) -> tuple[str, str]:
    try:
        return _sheets_to_markdown(_extract_xlsx_preview(file_path)), ""
    except Exception as error:
        return "", f"内置 XLSX 解析失败：{error}"


def _extract_material_content(file_path: Path, *, force_reparse: bool = False) -> dict[str, Any]:
    cached = None if force_reparse else _load_cached_parse(file_path)
    if cached is not None:
        return cached

    suffix = file_path.suffix.lower().lstrip(".")
    parser = ""
    text = ""
    errors: list[str] = []

    if suffix in TEXT_SUFFIXES:
        text = _normalize_extracted_text(file_path.read_text(encoding="utf-8", errors="replace"))
        parser = "内置文本读取"
    elif suffix in IMAGE_SUFFIXES:
        # 级联：RapidOCR 本地免费快筛 → 字符过少再走视觉模型。
        text, error = ocr_service.extract_image_with_rapidocr(file_path)
        if text:
            parser = "RapidOCR 本地 OCR"
        elif error:
            errors.append(error)
        if len(_normalize_extracted_text(text)) < ocr_service.OCR_MIN_CHARS_PER_PAGE:
            vision_text, vision_error = _extract_image_with_vision(file_path)
            if len(_normalize_extracted_text(vision_text)) > len(_normalize_extracted_text(text)):
                text = vision_text
                parser = "AI 视觉 OCR"
            if vision_error:
                errors.append(vision_error)
    elif suffix == "xlsx":
        if suffix in MARKITDOWN_SUFFIXES:
            text, error = _extract_with_markitdown(file_path)
            if text:
                parser = "MarkItDown"
            elif error:
                errors.append(error)
        if not text:
            text, error = _extract_native_xlsx(file_path)
            if text:
                parser = "内置 XLSX 解析"
            elif error:
                errors.append(error)
    elif suffix in MARKITDOWN_SUFFIXES:
        text, error = _extract_with_markitdown(file_path)
        if text:
            parser = "MarkItDown"
        elif error:
            errors.append(error)
        if not text and suffix in DOCLING_SUFFIXES:
            text, error = _extract_with_docling(file_path)
            if text:
                parser = "Docling"
            elif error:
                errors.append(error)
        if not text and suffix in {"xls"}:
            conversion = _convert_file_to_pdf(file_path)
            if conversion.get("available") and conversion.get("path"):
                pdf_path = Path(str(conversion["path"]))
                text, error = _extract_with_markitdown(pdf_path)
                if text:
                    parser = "LibreOffice PDF + MarkItDown"
                elif error:
                    errors.append(error)
        if not text and suffix == "pptx":
            slide_count, excerpt = _extract_pptx_excerpt(file_path)
            if excerpt:
                text = excerpt
                parser = f"内置 PPTX 文本读取（{slide_count} 页）"
    elif suffix == "ppt":
        conversion = _convert_file_to_pdf(file_path)
        if conversion.get("available") and conversion.get("path"):
            pdf_path = Path(str(conversion["path"]))
            text, error = _extract_with_markitdown(pdf_path)
            if text:
                parser = "LibreOffice PDF + MarkItDown"
            elif error:
                errors.append(error)
            if not text:
                text, error = _extract_with_docling(pdf_path)
                if text:
                    parser = "LibreOffice PDF + Docling"
                elif error:
                    errors.append(error)
        else:
            errors.append(str(conversion.get("reason", "旧版 PPT 需要先转换为 PDF。")))
    elif suffix == "pptx":
        slide_count, excerpt = _extract_pptx_excerpt(file_path)
        if excerpt:
            text = excerpt
            parser = f"内置 PPTX 文本读取（{slide_count} 页）"

    # 扫描版 PDF 兜底不能只判断“完全为空”：很多扫描教材只有水印或极少量
    # OCR 文本层，MarkItDown 会返回几十个字符并被误判为解析成功。按页数评估
    # 文本密度，明显过薄时对整份 PDF 做本地 OCR，并保留内容更完整的结果。
    if suffix == "pdf":
        normalized_pdf_text = _normalize_extracted_text(text)
        page_count = 1
        try:
            pymupdf, _ = ocr_service._get_pymupdf()
            if pymupdf is not None:
                pdf_document = pymupdf.open(str(file_path))
                try:
                    page_count = max(1, int(pdf_document.page_count))
                finally:
                    pdf_document.close()
        except Exception as error:
            errors.append(f"PDF 页数检测失败：{error}")
        minimum_expected = max(ocr_service.OCR_MIN_CHARS_PER_PAGE, page_count * 40)
        if len(normalized_pdf_text) < minimum_expected:
            ocr_text, ocr_parser, ocr_errors = _ocr_fallback_for_scanned_pdf(file_path)
            normalized_ocr_text = _normalize_extracted_text(ocr_text)
            if len(normalized_ocr_text) > len(normalized_pdf_text):
                text, parser = normalized_ocr_text, ocr_parser
            errors.extend(ocr_errors)

    parsed = {
        "parser": parser,
        "text": text,
        "parsedCharacters": len(text),
        "errors": errors[:3],
    }
    _save_cached_parse(file_path, parsed)
    return parsed


def _build_ai_status(file_path: Path, parsed: dict[str, Any]) -> dict[str, Any]:
    suffix = file_path.suffix.lower().lstrip(".")
    parsed_characters = int(parsed.get("parsedCharacters", 0))
    parser = str(parsed.get("parser", ""))
    errors = parsed.get("errors") if isinstance(parsed.get("errors"), list) else []

    if parsed_characters > 0:
        if parsed_characters < 80:
            return {
                "aiStatus": "partial",
                "aiLabel": "AI部分解析",
                "aiReadable": True,
                "aiMessage": f"已通过{parser}提取少量文字，内容可能不完整。",
            }
        return {
            "aiStatus": "ready",
            "aiLabel": "AI已解析",
            "aiReadable": True,
            "aiMessage": f"已通过{parser}提取 {parsed_characters} 个字符，可用于生成计划、题目和答疑上下文。",
        }

    if suffix in IMAGE_SUFFIXES:
        return {
            "aiStatus": "unreadable",
            "aiLabel": "AI未解析",
            "aiReadable": False,
            "aiMessage": f"图片视觉 OCR 未提取到内容。{f' 原因：{errors[0]}' if errors else ''}",
        }
    elif suffix == "pdf":
        message = "PDF 可预览，但未抽取到文字，OCR 级联（RapidOCR + 视觉模型）也未能提取内容。"
    elif suffix == "ppt":
        message = "旧版 PPT 需要 LibreOffice 转 PDF 后再解析；当前只记录文件名。"
    elif suffix == "xls":
        message = "旧版 XLS 需要 MarkItDown/xlrd 或转 PDF 后再解析；当前未进入 AI。"
    else:
        message = "该格式当前未进入 AI 解析上下文。"
    if errors:
        message = f"{message} 原因：{errors[0]}"
    return {
        "aiStatus": "unreadable",
        "aiLabel": "AI未解析",
        "aiReadable": False,
        "aiMessage": message,
    }


def _build_preview_status(file_path: Path, parsed: dict[str, Any]) -> dict[str, Any]:
    suffix = file_path.suffix.lower().lstrip(".")
    if suffix in IMAGE_SUFFIXES:
        return {
            "previewStatus": "ready",
            "previewLabel": "可预览",
            "previewMessage": "图片可直接在浏览器中预览。",
        }
    if suffix == "pdf":
        return {
            "previewStatus": "ready",
            "previewLabel": "可预览",
            "previewMessage": "PDF 可直接在浏览器中预览。",
        }
    if suffix in TEXT_SUFFIXES:
        return {
            "previewStatus": "ready",
            "previewLabel": "可预览",
            "previewMessage": "文本资料可直接预览。",
        }
    if suffix == "xlsx":
        return {
            "previewStatus": "ready",
            "previewLabel": "表格预览",
            "previewMessage": f"显示前 {XLSX_PREVIEW_MAX_ROWS} 行、{XLSX_PREVIEW_MAX_COLUMNS} 列。",
        }
    if suffix in OFFICE_TO_PDF_SUFFIXES:
        conversion = _convert_file_to_pdf(file_path)
        if conversion.get("available"):
            return {
                "previewStatus": "converted",
                "previewLabel": "PDF预览",
                "previewMessage": str(conversion.get("message", "已转换为 PDF 预览。")),
                "previewSource": "converted-pdf",
            }
        if parsed.get("text"):
            return {
                "previewStatus": "limited",
                "previewLabel": "文本预览",
                "previewMessage": "暂未生成 PDF，只显示已提取文本。",
            }
        return {
            "previewStatus": "unsupported",
            "previewLabel": "需转换",
            "previewMessage": str(conversion.get("reason", "该格式暂不支持站内预览。")),
        }
    return {
        "previewStatus": "unsupported",
        "previewLabel": "不可预览",
        "previewMessage": "该格式暂不支持站内预览，可尝试打开原文件。",
    }


def analyze_course_material(file_path: Path, *, force_reparse: bool = False) -> dict[str, Any]:
    suffix = file_path.suffix.lower().lstrip(".")
    parsed = _extract_material_content(file_path, force_reparse=force_reparse)
    ai_status = _build_ai_status(file_path, parsed)
    preview_status = _build_preview_status(file_path, parsed)
    detail = f"{ai_status['aiLabel']} · {preview_status['previewLabel']}"
    if parsed.get("parser"):
        detail = f"{detail} · {parsed['parser']}"
    return {
        "analysisVersion": MATERIAL_ANALYSIS_VERSION,
        "parser": parsed.get("parser", ""),
        "parsedCharacters": parsed.get("parsedCharacters", 0),
        "excerpt": str(parsed.get("text", "")),
        "detail": detail,
        **ai_status,
        **preview_status,
    }


def build_material_preview(relative_path: str, course_id: str) -> dict[str, Any]:
    file_path = resolve_course_material_path(relative_path, course_id)
    suffix = file_path.suffix.lower().lstrip(".")
    analysis = analyze_course_material(file_path)
    parsed_content = _extract_material_content(file_path)
    preview: dict[str, Any] = {
        "name": file_path.name,
        "relativePath": _relative_material_path(file_path, course_id),
        "type": suffix.upper() if suffix else "FILE",
        "aiStatus": analysis["aiStatus"],
        "aiLabel": analysis["aiLabel"],
        "aiMessage": analysis["aiMessage"],
        "previewStatus": analysis["previewStatus"],
        "previewLabel": analysis["previewLabel"],
        "previewMessage": analysis["previewMessage"],
    }

    if analysis.get("previewSource") == "converted-pdf":
        return {
            **preview,
            "kind": "pdf",
            "isConvertedPreview": True,
            "message": analysis["previewMessage"],
        }
    if suffix in IMAGE_SUFFIXES:
        return {
            **preview,
            "kind": "image",
            "message": analysis["previewMessage"],
        }
    if suffix == "pdf":
        return {
            **preview,
            "kind": "pdf",
            "message": analysis["previewMessage"],
        }
    if suffix in TEXT_SUFFIXES:
        return {
            **preview,
            "kind": "text",
            "text": parsed_content.get("text", analysis.get("excerpt", "")),
            "message": analysis["previewMessage"],
        }
    if suffix == "pptx":
        return {
            **preview,
            "kind": "text",
            "text": parsed_content.get("text", analysis.get("excerpt", "")) or "未能从该课件中提取到可预览文字。",
            "message": analysis["previewMessage"],
        }
    if suffix == "xlsx":
        try:
            sheets = _extract_xlsx_preview(file_path)
        except Exception:
            sheets = []
        if sheets:
            return {
                **preview,
                "kind": "sheet",
                "sheets": sheets,
                "message": analysis["previewMessage"],
            }
        return {
            **preview,
            "kind": "unsupported",
            "message": "这个 Excel 文件没有可显示的工作表内容。",
        }
    if analysis.get("excerpt") and analysis["previewStatus"] == "limited":
        return {
            **preview,
            "kind": "text",
            "text": parsed_content.get("text", analysis.get("excerpt", "")),
            "message": analysis["previewMessage"],
        }

    return {
        **preview,
        "kind": "unsupported",
        "message": analysis["previewMessage"],
    }
