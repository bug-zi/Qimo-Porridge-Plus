"""本地 OCR 级联解析：扫描版 PDF / 图片 → RapidOCR 免费快筛 → 视觉模型兜底。

设计目标与 study_scheduler 一致：本地、离线、确定性优先。
- PyMuPDF 负责把 PDF 每页渲染成位图（不联网）。
- RapidOCR（onnxruntime）负责印刷体识别：免费、快，覆盖 90% 的扫描件。
- 只有当 RapidOCR 每页识别字符数过低（版面复杂/手写）时，才升级调用
  用户配置的视觉模型逐页兜底，控制 API 成本。

所有入口都是可选依赖：未安装 rapidocr_onnxruntime / pymupdf 时返回
清晰的不可用原因，不影响原有解析链路。
"""

from __future__ import annotations

import base64
import mimetypes
import threading
from pathlib import Path
from typing import Any, Callable

# RapidOCR 每页字符数低于该阈值视为"识别失败"，升级视觉模型兜底。
OCR_MIN_CHARS_PER_PAGE = 200
# 视觉兜底单文件最多处理的页数（防止几十页扫描册烧钱）。
VISION_FALLBACK_MAX_PAGES = 30
# PDF 渲染 DPI（150 对印刷体扫描件足够，300 速度减半收益有限）。
PDF_RENDER_DPI = 150
# 默认处理整份 PDF，避免长扫描教材只索引前几十页。可通过环境变量显式限制。
# 0 表示不限制；视觉模型兜底仍由 VISION_FALLBACK_MAX_PAGES 单独限流。
import os
PDF_RENDER_MAX_PAGES = max(0, int(os.getenv("PDF_OCR_MAX_PAGES", "0")))


def _page_limit(page_count: int) -> int:
    return min(page_count, PDF_RENDER_MAX_PAGES) if PDF_RENDER_MAX_PAGES else page_count

_RAPIDOCR_LOCK = threading.Lock()
_RAPIDOCR_INSTANCE: Any | None = None
_RAPIDOCR_ERROR = ""

_PYMUPDF_ERROR = ""
_PYMUPDF_CHECKED = False


def _get_rapidocr() -> tuple[Any | None, str]:
    """懒加载 RapidOCR 引擎（首次约 1-2 秒，模型内置无需下载）。"""
    global _RAPIDOCR_INSTANCE, _RAPIDOCR_ERROR
    if _RAPIDOCR_INSTANCE is not None:
        return _RAPIDOCR_INSTANCE, ""
    if _RAPIDOCR_ERROR:
        return None, _RAPIDOCR_ERROR
    with _RAPIDOCR_LOCK:
        if _RAPIDOCR_INSTANCE is not None:
            return _RAPIDOCR_INSTANCE, ""
        if _RAPIDOCR_ERROR:
            return None, _RAPIDOCR_ERROR
        try:
            try:
                from rapidocr import RapidOCR
            except ImportError:  # 兼容 Python 3.12 及以下的旧发行包
                from rapidocr_onnxruntime import RapidOCR

            _RAPIDOCR_INSTANCE = RapidOCR()
        except Exception as error:  # pragma: no cover - 依赖缺失场景
            _RAPIDOCR_ERROR = f"RapidOCR 未安装或不可用：{error}（pip install rapidocr）"
            return None, _RAPIDOCR_ERROR
    return _RAPIDOCR_INSTANCE, ""


def _get_pymupdf() -> tuple[Any | None, str]:
    """懒加载 PyMuPDF（fitz 模块）。"""
    global _PYMUPDF_ERROR, _PYMUPDF_CHECKED
    if _PYMUPDF_CHECKED:
        return (None, _PYMUPDF_ERROR) if _PYMUPDF_ERROR else (_import_pymupdf(), "")
    _PYMUPDF_CHECKED = True
    try:
        module = _import_pymupdf()
        if module is None:
            raise ImportError("pymupdf 不可用")
    except Exception as error:  # pragma: no cover - 依赖缺失场景
        _PYMUPDF_ERROR = f"PyMuPDF 未安装或不可用：{error}（pip install pymupdf）"
        return None, _PYMUPDF_ERROR
    return _import_pymupdf(), ""


def _import_pymupdf() -> Any:
    try:
        import pymupdf  # 1.28+ 推荐入口

        return pymupdf
    except ImportError:
        import fitz  # 兼容旧版

        return fitz


def _rapidocr_image_bytes(engine: Any, image_bytes: bytes) -> str:
    """用 RapidOCR 识别一张 PNG（渲染产物），返回按行拼接的文本。

    RapidOCR 原生支持 bytes 输入（内部 cv2.imdecode 自动解码 PNG）。
    """
    output = engine(image_bytes)
    # rapidocr 3.x 返回 RapidOCROutput；旧 rapidocr-onnxruntime 返回 (result, elapsed)。
    modern_texts = getattr(output, "txts", None)
    if modern_texts is not None:
        return "\n".join(str(text).strip() for text in modern_texts if str(text).strip())
    result = output[0] if isinstance(output, tuple) else output
    if not result:
        return ""
    lines: list[str] = []
    for item in result:
        text = str(item[1]).strip() if len(item) > 1 else ""
        if text:
            lines.append(text)
    return "\n".join(lines)


def _rapidocr_image_file(engine: Any, image_path: Path) -> str:
    """用 RapidOCR 识别磁盘上的图片文件（RapidOCR 自带图片读取）。"""
    result, _ = engine(str(image_path))
    if not result:
        return ""
    lines: list[str] = []
    for item in result:
        text = str(item[1]).strip() if len(item) > 1 else ""
        if text:
            lines.append(text)
    return "\n".join(lines)


def extract_scanned_pdf_with_rapidocr(file_path: Path) -> tuple[str, str]:
    """扫描版 PDF → 每页渲染位图 → RapidOCR。返回 (text, error)。

    只负责本地快筛，不做视觉模型兜底；调用方根据字符数决定是否升级。
    """
    pymupdf, error = _get_pymupdf()
    if pymupdf is None:
        return "", error
    engine, error = _get_rapidocr()
    if engine is None:
        return "", error
    try:
        doc = pymupdf.open(str(file_path))
    except Exception as open_error:
        return "", f"PDF 打开失败：{open_error}"
    try:
        sections: list[str] = []
        page_count = _page_limit(doc.page_count)
        for page_index in range(page_count):
            page = doc.load_page(page_index)
            zoom = PDF_RENDER_DPI / 72
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            image_bytes = pixmap.tobytes("png")
            page_text = _rapidocr_image_bytes(engine, image_bytes)
            if page_text:
                sections.append(f"<!-- 第 {page_index + 1} 页 -->\n{page_text}")
        return "\n\n".join(sections), ""
    except Exception as render_error:
        return "", f"RapidOCR 解析 PDF 失败：{render_error}"
    finally:
        doc.close()


def extract_image_with_rapidocr(file_path: Path) -> tuple[str, str]:
    """单张图片 → RapidOCR（先于视觉模型的免费快筛）。"""
    engine, error = _get_rapidocr()
    if engine is None:
        return "", error
    try:
        text = _rapidocr_image_file(engine, file_path)
        return text, ""
    except Exception as run_error:
        return "", f"RapidOCR 解析图片失败：{run_error}"


def render_pdf_pages_as_images(file_path: Path) -> list[tuple[int, bytes]]:
    """PDF 逐页渲染为 PNG 字节，供视觉模型兜底使用。

    返回 [(页码(1-based), png_bytes)]；空列表表示渲染失败或无页。
    """
    pymupdf, error = _get_pymupdf()
    if pymupdf is None:
        return []
    try:
        doc = pymupdf.open(str(file_path))
    except Exception:
        return []
    try:
        pages: list[tuple[int, bytes]] = []
        zoom = PDF_RENDER_DPI / 72
        count = _page_limit(doc.page_count)
        for page_index in range(count):
            page = doc.load_page(page_index)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            pages.append((page_index + 1, pixmap.tobytes("png")))
        return pages
    finally:
        doc.close()


def extract_pdf_pages_for_vision(
    file_path: Path,
    page_numbers: list[int],
    completion: Callable[[list[dict[str, Any]]], str],
) -> tuple[str, str]:
    """把指定页渲染成图后交给视觉模型 completion 兜底 OCR。

    completion 接收 OpenAI 格式 messages（含 image_url），返回模型文本；
    这样本模块不需要知道模型配置，保持与 study_service 解耦。
    """
    pymupdf, error = _get_pymupdf()
    if pymupdf is None:
        return "", error
    try:
        doc = pymupdf.open(str(file_path))
    except Exception as open_error:
        return "", f"PDF 打开失败：{open_error}"
    try:
        zoom = PDF_RENDER_DPI / 72
        sections: list[str] = []
        last_error = ""
        for page_number in page_numbers[:VISION_FALLBACK_MAX_PAGES]:
            if page_number < 1 or page_number > doc.page_count:
                continue
            page = doc.load_page(page_number - 1)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            image_data = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"请解析这份扫描资料的第 {page_number} 页图片，"
                                "完整转写为可检索的 Markdown 文本（保留题目顺序、选项、表格与公式，"
                                "不要解题，不要输出无关开场）。"
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_data}"},
                        },
                    ],
                }
            ]
            try:
                text = completion(messages)
            except Exception as call_error:
                last_error = f"第 {page_number} 页视觉 OCR 失败：{call_error}"
                continue
            if text:
                sections.append(f"<!-- 第 {page_number} 页 -->\n{text}")
        if not sections:
            return "", last_error or "视觉模型未能从扫描页中提取到内容"
        return "\n\n".join(sections), ""
    finally:
        doc.close()


def guess_image_mime(file_path: Path) -> str:
    return mimetypes.guess_type(file_path.name)[0] or "image/png"


def rapidocr_available() -> bool:
    engine, error = _get_rapidocr()
    return engine is not None


def summarize_ocr_pages(text: str) -> tuple[int, int]:
    """统计 OCR 文本中的页标记数与平均每页字符数，用于状态展示。"""
    page_count = text.count("<!-- 第 ")
    if page_count == 0:
        stripped = text.replace("\n", "")
        return (1, len(stripped)) if stripped else (0, 0)
    body = text.replace("<!-- 第 ", "\x00<!-- 第 ")
    pages = [chunk.split("-->", 1)[-1] for chunk in body.split("\x00")[1:]] or [""]
    avg = sum(len(page.replace("\n", "")) for page in pages) // max(1, len(pages))
    return len(pages), avg
