"""扫描版 PDF / 图片 OCR 级联解析测试。

用 PyMuPDF 动态构造"无文本层的扫描版 PDF"（把文字先渲染成位图再贴进
PDF 页面），验证 ocr_service 的渲染识别链路与 study_service 的级联
接入，不依赖任何磁盘测试夹具。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ocr_service  # noqa: E402

pymupdf = pytest.importorskip("pymupdf", reason="需要 pymupdf 构造扫描 PDF 夹具")


def _render_text_page(doc: Any, lines: list[str]) -> None:
    """把文字画到临时页面，再以图片形式贴进目标页（无文本层）。"""
    temp = pymupdf.open()
    temp_page = temp.new_page(width=612, height=792)
    y = 90
    for line in lines:
        temp_page.insert_text((72, y), line, fontsize=16)
        y += 34
    pix = temp_page.get_pixmap(matrix=pymupdf.Matrix(150 / 72, 150 / 72))
    page = doc.new_page(width=612, height=792)
    page.insert_image(pymupdf.Rect(0, 0, 612, 792), stream=pix.tobytes("png"))
    temp.close()


def _make_scanned_pdf(path: Path, pages: list[list[str]]) -> Path:
    doc = pymupdf.open()
    for lines in pages:
        _render_text_page(doc, lines)
    doc.save(str(path))
    doc.close()
    return path


class TestRapidOcrPipeline:
    def test_scanned_pdf_extracted_locally(self, tmp_path: Path) -> None:
        """扫描 PDF（图片页）能被 RapidOCR 提取出文字并带页标记。"""
        engine, error = ocr_service._get_rapidocr()
        if engine is None:
            pytest.skip(f"RapidOCR 不可用：{error}")
        pdf_path = _make_scanned_pdf(
            tmp_path / "scanned.pdf",
            [
                ["Comprehensive Final Exam", "Reading Comprehension Basics"],
                ["Chapter 3 Evidence Analysis", "Written Response Method"],
            ],
        )
        text, extract_error = ocr_service.extract_scanned_pdf_with_rapidocr(pdf_path)
        assert extract_error == ""
        assert "Comprehensive" in text
        assert "<!-- 第 1 页 -->" in text
        assert "<!-- 第 2 页 -->" in text
        assert "Evidence" in text

    def test_text_pdf_also_readable(self, tmp_path: Path) -> None:
        """普通文本 PDF 走 OCR 也能出字（渲染的是位图，同样可识别）。"""
        engine, error = ocr_service._get_rapidocr()
        if engine is None:
            pytest.skip(f"RapidOCR 不可用：{error}")
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 100), "Critical Reading and Review", fontsize=16)
        pdf_path = tmp_path / "text-based.pdf"
        doc.save(str(pdf_path))
        doc.close()
        text, extract_error = ocr_service.extract_scanned_pdf_with_rapidocr(pdf_path)
        assert extract_error == ""
        assert "Reading" in text


class TestSummarizeOcrPages:
    def test_page_marker_statistics(self) -> None:
        text = "<!-- 第 1 页 -->\nabc\n\n<!-- 第 2 页 -->\ndefgh"
        pages, avg = ocr_service.summarize_ocr_pages(text)
        assert pages == 2
        assert avg == 4  # (3 + 5) / 2

    def test_no_marker_single_page(self) -> None:
        pages, avg = ocr_service.summarize_ocr_pages("hello world")
        assert pages == 1
        assert avg == 11

    def test_empty_text(self) -> None:
        assert ocr_service.summarize_ocr_pages("") == (0, 0)


class TestVisionFallbackSelection:
    def test_weak_page_numbers_sorted_by_size(self) -> None:
        """页体积排序逻辑：最薄的页应排在兜底列表最前。"""
        normalized = (
            "<!-- 第 1 页 -->\n" + "a" * 500 + "\n\n"
            "<!-- 第 2 页 -->\n" + "b" * 30 + "\n\n"
            "<!-- 第 3 页 -->\n" + "c" * 400
        )
        sections = normalized.split("<!-- 第 ")[1:]
        sizes = []
        for index, section in enumerate(sections, start=1):
            body = section.split("-->", 1)[-1] if "-->" in section else section
            sizes.append((len(body.strip()), index))
        weak = [number for _, number in sorted(sizes)[: ocr_service.VISION_FALLBACK_MAX_PAGES]]
        assert weak[0] == 2  # 最薄的第 2 页优先兜底


class TestStudyServiceIntegration:
    """端到端：扫描 PDF 在 study_service 解析链路中被 OCR 接管。"""

    DENSE_LINES = [
        "Comprehensive Final Examination 2026",
        "Part I: Multiple Choice Questions (40 points)",
        "1. Read each question carefully and identify the main idea",
        "   before selecting the best answer from the available choices.",
        "2. Compare the evidence provided in the source material and",
        "   choose the conclusion that is supported by all stated facts.",
        "3. When two explanations appear plausible, review their scope",
        "   and determine which one applies to the given conditions.",
        "4. Organize the response with a clear claim and supporting details",
        "   so that every step can be checked against the prompt.",
        "Part II: Written Response Questions (60 points)",
        "5. Summarize the passage in your own words and explain how the",
        "   examples support its central idea in a complete paragraph.",
    ]

    def test_dense_scanned_pdf_handled_by_rapidocr(self, tmp_path: Path) -> None:
        """文字量充足的扫描 PDF 停留在 RapidOCR，不触发视觉模型。"""
        study_service = pytest.importorskip(
            "app.study_service", reason="study_service 导入失败"
        )
        engine, error = ocr_service._get_rapidocr()
        if engine is None:
            pytest.skip(f"RapidOCR 不可用：{error}")
        temp = pymupdf.open()
        temp_page = temp.new_page(width=612, height=792)
        for index, line in enumerate(self.DENSE_LINES):
            temp_page.insert_text((72, 80 + index * 36), line, fontsize=13)
        pix = temp_page.get_pixmap(matrix=pymupdf.Matrix(150 / 72, 150 / 72))
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        page.insert_image(pymupdf.Rect(0, 0, 612, 792), stream=pix.tobytes("png"))
        pdf_path = tmp_path / "dense-scanned.pdf"
        doc.save(str(pdf_path))
        doc.close()
        temp.close()

        # 夹具自检：确认确实无文本层（MarkItDown 对它无能为力）
        check = pymupdf.open(str(pdf_path))
        assert len(check.load_page(0).get_text().strip()) == 0
        check.close()

        parsed = study_service._extract_material_content(pdf_path)
        assert "RapidOCR" in parsed["parser"]
        assert parsed["parsedCharacters"] > 200
        assert "Question" in parsed["text"] or "question" in parsed["text"]


class TestDependenciesOptional:
    def test_rapidocr_available_reports_state(self) -> None:
        """可用性探测不应抛异常，只返回布尔。"""
        assert isinstance(ocr_service.rapidocr_available(), bool)
