"""路径与数据目录常量的唯一定义点（阶段2-1 抽取）。

为什么单独成模块：DATA_DIRECTORY / COURSES_DATA_DIRECTORY / MATERIAL_CACHE_DIRECTORY
此前定义在 study_service.py，测试通过 monkeypatch.setattr(study_service, "DATA_DIRECTORY", ...)
隔离数据目录。拆分后多个模块（materials / material_parser / model_profiles …）都要用这些
常量，若各自持有副本，patch 门面就再也管不到新模块——测试会悄悄写进真实数据库。
因此收敛到本模块，所有消费方一律 `from . import paths` 后用 `paths.DATA_DIRECTORY`
（模块属性访问，测试 patch paths 拥有者即可全局生效）。

约束：本模块不 import 项目内任何其他模块，保持零依赖。
"""
from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent

DATA_DIRECTORY = BACKEND_ROOT / "data"
COURSES_DATA_DIRECTORY = DATA_DIRECTORY / "courses"
RUNTIME_ENV_PATH = BACKEND_ROOT / ".env"
MATERIAL_CACHE_DIRECTORY = DATA_DIRECTORY / "material_cache"
MODEL_PROFILES_PATH = DATA_DIRECTORY / "model_profiles.json"
DATABASE_PATH = DATA_DIRECTORY / "exam_booster.db"
