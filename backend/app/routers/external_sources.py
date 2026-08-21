from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..agent_runtime import get_external_source
from ..external_source_service import (
    approve_external_source,
    dismiss_external_source,
    submit_external_source,
)
from ..study_service import load_workspace
from .deps import require_course_ownership

router = APIRouter()


class ExternalSourceRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    mcp_server_id: str = Field(min_length=1, max_length=120)
    tool_name: str = Field(min_length=1, max_length=200)
    source_type: Literal["web", "video", "note"] = "web"


@router.post("/api/courses/{course_id}/external-sources", status_code=202)
def import_external_course_source(
    course_id: str,
    payload: ExternalSourceRequest,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        load_workspace(course_id, refresh_materials=False)
        return submit_external_source(
            course_id,
            payload.url,
            server_id=payload.mcp_server_id,
            tool_name=payload.tool_name,
            source_type=payload.source_type,
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/api/courses/{course_id}/external-sources/{source_id}")
def external_course_source(
    course_id: str,
    source_id: str,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return get_external_source(course_id, source_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/api/courses/{course_id}/external-sources/{source_id}/approve")
def approve_external_course_source(
    course_id: str,
    source_id: str,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return approve_external_source(course_id, source_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/api/courses/{course_id}/external-sources/{source_id}/dismiss")
def dismiss_external_course_source(
    course_id: str,
    source_id: str,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return dismiss_external_source(course_id, source_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
