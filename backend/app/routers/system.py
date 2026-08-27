from __future__ import annotations

from fastapi import APIRouter

from ..study_service import get_model_usage

router = APIRouter()


@router.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "exam-booster-local-api"}


@router.get("/api/model-usage")
def model_usage() -> dict:
    """模型调用 token 用量快照（进程级累计 + 最近调用明细），供生成进度展示轮询。"""
    return get_model_usage()
