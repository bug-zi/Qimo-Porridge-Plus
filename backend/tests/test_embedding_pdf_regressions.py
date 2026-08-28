from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import knowledge_service, material_parser, ocr_service, study_service


def test_pdf_page_limit_defaults_to_complete_document() -> None:
    assert ocr_service._page_limit(371) == (
        min(371, ocr_service.PDF_RENDER_MAX_PAGES)
        if ocr_service.PDF_RENDER_MAX_PAGES
        else 371
    )


def test_sparse_pdf_text_layer_triggers_ocr(monkeypatch, tmp_path: Path) -> None:
    pymupdf, error = ocr_service._get_pymupdf()
    assert pymupdf is not None, error
    pdf_path = tmp_path / "sparse-text-layer.pdf"
    document = pymupdf.open()
    for index in range(5):
        page = document.new_page()
        if index == 0:
            page.insert_text((72, 72), "watermark")
    document.save(str(pdf_path))
    document.close()

    # 解析器实现已搬到 material_parser.py（阶段2-2），打桩 patch 本体模块。
    monkeypatch.setattr(material_parser, "_extract_with_markitdown", lambda _path: ("watermark", ""))
    monkeypatch.setattr(
        material_parser,
        "_ocr_fallback_for_scanned_pdf",
        lambda _path: ("完整正文" * 300, "RapidOCR 本地 OCR（5 页）", []),
    )

    parsed = material_parser._extract_material_content(pdf_path, force_reparse=True)
    assert parsed["parser"] == "RapidOCR 本地 OCR（5 页）"
    assert parsed["parsedCharacters"] == len("完整正文" * 300)


def test_embedding_counts_can_be_scoped_to_course(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "knowledge.db"
    embedding_path = tmp_path / "embeddings.db"
    monkeypatch.setattr(knowledge_service, "DATABASE_PATH", database_path)
    monkeypatch.setattr(knowledge_service, "EMBEDDING_CACHE_PATH", embedding_path)
    knowledge_service.initialize_knowledge_database()
    with knowledge_service._database_connection() as connection:
        for course_id, chunk_id in (("course-a", "a-1"), ("course-a", "a-2"), ("course-b", "b-1")):
            connection.execute(
                """INSERT INTO material_chunks
                (id, course_id, relative_path, material_name, chunk_index, locator,
                 heading, content, content_hash, role, priority_order, created_at)
                VALUES (?, ?, 'book.pdf', 'book.pdf', 1, '第 1 段', '', 'text', ?,
                        'primary', 1, '2026-01-01')""",
                (chunk_id, course_id, chunk_id),
            )
    with knowledge_service._embedding_connection() as connection:
        connection.execute(
            """INSERT INTO chunk_embeddings
            (chunk_id, model, content_hash, dimension, vector_json, updated_at)
            VALUES ('a-1', 'bge-m3', 'a-1', 1024, '[1]', '2026-01-01')"""
        )
        connection.execute(
            """INSERT INTO chunk_embeddings
            (chunk_id, model, content_hash, dimension, vector_json, updated_at)
            VALUES ('b-1', 'bge-m3', 'b-1', 1024, '[1]', '2026-01-01')"""
        )

    assert knowledge_service._embedding_counts("bge-m3", "course-a") == (1, 2, 1024)
    assert knowledge_service._embedding_counts("bge-m3", "course-b") == (1, 1, 1024)
