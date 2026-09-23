"""pytest 全局夹具：测试与真实数据目录隔离。

backend/data/ 是用户的真实学习数据（见项目 CLAUDE.md「数据安全」），
任何测试不得写入。资料解析缓存 MATERIAL_CACHE_DIRECTORY 默认指向真实目录，
个别测试（test_ocr_service / test_embedding_pdf_regressions）会经
_extract_material_content → _save_cached_parse 真实落盘，历史上每次
全量测试都在真实缓存目录净增垃圾文件（2026-08-27~09-01 累计 157 个，
见 docs/log/260901.md）。

本夹具 autouse 生效：把缓存目录重定向到每个测试各自的 tmp_path，
测试写缓存在临时目录内自生自灭，不触碰真实数据。新增测试无需再
单独 monkeypatch（test_course_feedback_router / test_multi_tenant_
isolation 里的手动 patch 保留不动，重复指向临时目录无害）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import paths  # noqa: E402


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "no_material_cache_isolation: 豁免缓存目录隔离（用于断言 paths 默认接线的门面契约测试）",
    )


@pytest.fixture(autouse=True)
def _isolate_material_cache(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """把资料解析缓存重定向到测试专属临时目录，不触碰 backend/data/ 真实数据。

    门面契约测试（test_facade_exports）断言的是 paths 模块的默认接线，
    需要看到未打补丁的真实常量，用 no_material_cache_isolation 标记豁免。
    """
    if request.node.get_closest_marker("no_material_cache_isolation"):
        return
    monkeypatch.setattr(paths, "MATERIAL_CACHE_DIRECTORY", tmp_path / "material_cache")
