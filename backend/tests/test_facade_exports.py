r"""study_service 门面契约测试（阶段2-1）。

拆分 study_service.py 的核心策略是"旧文件保留 re-export 门面，外部 import 零改动"。
本测试锁定门面必须继续暴露的符号——若某个 re-export 被误删，这里立刻红，
而不是等到某个 router import 时才炸。

同时锁定新模块的依赖方向约束（model_profiles 不得 import study_service）。
运行：cd backend && .venv\Scripts\python -m pytest tests/test_facade_exports.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import material_parser, materials, model_profiles, paths, practice, study_service


def test_paths_module_is_sole_owner_of_directory_constants() -> None:
    """路径常量收敛点：paths 定义、study_service 门面别名、值一致。"""
    assert paths.BACKEND_ROOT.name == "backend"
    assert paths.DATA_DIRECTORY == paths.BACKEND_ROOT / "data"
    assert paths.COURSES_DATA_DIRECTORY == paths.DATA_DIRECTORY / "courses"
    assert paths.MATERIAL_CACHE_DIRECTORY == paths.DATA_DIRECTORY / "material_cache"
    assert paths.MODEL_PROFILES_PATH == paths.DATA_DIRECTORY / "model_profiles.json"
    assert paths.DATABASE_PATH == paths.DATA_DIRECTORY / "exam_booster.db"

    # study_service 上的别名仍然指向同一份值（旧 import/调用方兼容）。
    assert study_service.DATA_DIRECTORY == paths.DATA_DIRECTORY
    assert study_service.COURSES_DATA_DIRECTORY == paths.COURSES_DATA_DIRECTORY
    assert study_service.RUNTIME_ENV_PATH == paths.RUNTIME_ENV_PATH
    assert study_service.MATERIAL_CACHE_DIRECTORY == paths.MATERIAL_CACHE_DIRECTORY


def test_study_service_facade_reexports_model_profiles_domain() -> None:
    """模型配置/用户画像域符号必须继续可从 study_service 导入。"""
    facade_symbols = [
        "MODEL_PROFILES_PATH",
        "PLATFORM_SYSTEM_PROMPT",
        "USER_PROFILE_PROMPT_METADATA_KEY",
        "USER_PROFILE_PROMPT_MAX_LENGTH",
        "_metadata_connection",
        "_ensure_app_metadata_table",
        "_user_profile_metadata_key",
        "get_user_profile_prompt",
        "save_user_profile_prompt",
        "build_model_messages",
        "get_runtime_model_api_key",
        "resolve_api_key_for_base_url",
        "save_runtime_model_profile",
        "get_runtime_model_profile",
        "_load_model_profile_store",
        "_persist_model_profile_store",
        "_rewrite_env_lines",
        "_activate_model_profile_values",
        "get_model_profiles",
        "save_model_profile",
    ]
    for name in facade_symbols:
        assert hasattr(study_service, name), f"门面缺失符号: {name}"
        assert getattr(study_service, name) is getattr(model_profiles, name), (
            f"{name} 不是 model_profiles 本体的同一对象（re-export 被副本覆盖）"
        )


def test_model_profiles_module_does_not_import_study_service() -> None:
    """依赖方向约束：model_profiles → model_client/paths，禁止反向依赖形成环。"""
    assert "study_service" not in getattr(model_profiles, "__dict__", {})


def test_build_model_messages_is_injected_into_model_client() -> None:
    """set_message_builder 注入的是 model_profiles.build_model_messages 本体。"""
    from app import model_client

    assert model_client._MESSAGE_BUILDER is model_profiles.build_model_messages


def test_study_service_facade_reexports_material_parser_domain() -> None:
    """资料解析域符号必须继续可从 study_service 导入且为同一对象。"""
    facade_symbols = [
        "MATERIAL_ANALYSIS_VERSION",
        "TEXT_SUFFIXES",
        "IMAGE_SUFFIXES",
        "MARKITDOWN_SUFFIXES",
        "DOCLING_SUFFIXES",
        "OFFICE_TO_PDF_SUFFIXES",
        "XLSX_PREVIEW_MAX_ROWS",
        "XLSX_PREVIEW_MAX_COLUMNS",
        "SPREADSHEET_NAMESPACE",
        "_convert_file_to_pdf",
        "_extract_image_with_vision",
        "_extract_material_content",
        "_extract_native_xlsx",
        "_extract_pptx_excerpt",
        "_extract_with_docling",
        "_extract_with_markitdown",
        "_extract_xlsx_preview",
        "_load_cached_parse",
        "_material_cache_key",
        "_material_cache_path",
        "_normalize_extracted_text",
        "_ocr_fallback_for_scanned_pdf",
        "_relative_material_path",
        "_save_cached_parse",
        "_sheets_to_markdown",
        "analyze_course_material",
        "build_material_preview",
        "resolve_converted_material_pdf_path",
        "resolve_course_material_path",
    ]
    for name in facade_symbols:
        assert hasattr(study_service, name), f"门面缺失符号: {name}"
        assert getattr(study_service, name) is getattr(material_parser, name), (
            f"{name} 不是 material_parser 本体的同一对象（re-export 被副本覆盖）"
        )


def test_material_parser_module_does_not_import_study_service() -> None:
    """依赖方向约束：material_parser 模块级不依赖 study_service（环检查）。"""
    assert "study_service" not in getattr(material_parser, "__dict__", {})


def test_study_service_facade_reexports_materials_domain() -> None:
    """资料管理域符号必须继续可从 study_service 导入且为同一对象。"""
    facade_symbols = [
        "MAX_SINGLE_MATERIAL_BYTES",
        "MAX_BATCH_MATERIAL_BYTES",
        "MATERIAL_ROLE_PRIMARY",
        "MATERIAL_ROLE_SUPPLEMENTARY",
        "MATERIAL_ROLE_VALUES",
        "_apply_material_roles",
        "_build_material_memory",
        "_mark_material_memory",
        "_material_digest",
        "_material_role_metadata",
        "_normalize_material_role",
        "_safe_upload_material_name",
        "_workspace_needs_material_refresh",
        "delete_course_material",
        "refresh_workspace_materials",
        "scan_course_materials",
        "sync_course_knowledge",
        "update_course_material_role",
        "upload_course_material",
        "upload_course_materials",
    ]
    for name in facade_symbols:
        assert hasattr(study_service, name), f"门面缺失符号: {name}"
        assert getattr(study_service, name) is getattr(materials, name), (
            f"{name} 不是 materials 本体的同一对象（re-export 被副本覆盖）"
        )


def test_materials_module_does_not_import_study_service() -> None:
    """依赖方向约束：materials 模块级不依赖 study_service（环检查）。"""
    assert "study_service" not in getattr(materials, "__dict__", {})


def test_study_service_facade_reexports_workspace_domain() -> None:
    """工作空间域符号必须继续可从 study_service 导入且为同一对象。"""
    from app import workspace

    facade_symbols = [
        "WORKSPACE_CONTENT_VERSION",
        "_CONTENT_GENERATION_LOCKS",
        "_CONTENT_GENERATION_LOCKS_GUARD",
        "_WORKSPACE_LOCKS",
        "_WORKSPACE_LOCKS_GUARD",
        "_atomic_write_text",
        "_build_study_guide_sections",
        "_clear_pre_plan_content",
        "_complete_study_guide",
        "_content_generation_lock",
        "_course_data_directory",
        "_course_material_directory",
        "_course_overview_path",
        "_empty_course_workspace",
        "_ensure_workspace_content_quality",
        "_mind_map_path",
        "_reshuffle_unanswered_single_choice",
        "_review_days_from_exam_date",
        "_strategy_directory",
        "_validate_course_id",
        "_workspace_is_planned",
        "_workspace_lock",
        "_workspace_path",
        "create_course_workspace",
        "create_empty_course_workspace",
        "load_mind_map",
        "load_workspace",
        "save_mind_map",
        "save_workspace",
    ]
    for name in facade_symbols:
        assert hasattr(study_service, name), f"门面缺失符号: {name}"
        assert getattr(study_service, name) is getattr(workspace, name), (
            f"{name} 不是 workspace 本体的同一对象（re-export 被副本覆盖）"
        )


def test_workspace_module_does_not_import_study_service() -> None:
    """依赖方向约束：workspace 模块级不依赖 study_service（环检查）。"""
    from app import workspace

    assert "study_service" not in getattr(workspace, "__dict__", {})


def test_study_service_facade_reexports_practice_domain() -> None:
    """练习/错题/模拟卷域符号必须继续可从 study_service 导入且为同一对象。"""
    facade_symbols = [
        "_ai_review_wrong_answer",
        "_answer_label",
        "_append_practice_questions",
        "_estimate_score",
        "_find_any_question",
        "_find_question",
        "_grade_mock_written_answer",
        "_is_written_mock_question",
        "_knowledge_point_name",
        "_normalize_generated_practice_questions",
        "_prioritize_tasks",
        "_record_written_wrong_answer",
        "_record_wrong_answer",
        "_update_mastery",
        "clear_mock_result",
        "clear_practice_answer",
        "repair_course_mock_questions",
        "submit_mock_answers",
        "submit_practice_answer",
        "submit_wrong_answer_retry",
    ]
    for name in facade_symbols:
        assert hasattr(study_service, name), f"门面缺失符号: {name}"
        assert getattr(study_service, name) is getattr(practice, name), (
            f"{name} 不是 practice 本体的同一对象（re-export 被副本覆盖）"
        )


def test_practice_module_does_not_import_study_service() -> None:
    """依赖方向约束：practice 模块级不依赖 study_service（环检查）。"""
    assert "study_service" not in getattr(practice, "__dict__", {})
