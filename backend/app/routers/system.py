from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "exam-booster-local-api"}
