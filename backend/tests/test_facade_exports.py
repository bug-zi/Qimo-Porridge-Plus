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

from app import model_profiles, paths, study_service


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
