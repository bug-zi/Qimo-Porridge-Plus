from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request as FastAPIRequest
from fastapi.responses import FileResponse

from ..agent_runtime import enqueue_agent_job
from ..study_service import (
    build_material_preview,
    delete_course_material,
    mark_strategy_maintenance_pending,
    refresh_workspace_materials,
    resolve_converted_material_pdf_path,
    resolve_course_material_path,
    update_course_material_role,
    upload_course_materials,
)
from .deps import require_course_ownership

router = APIRouter()


@router.get("/api/courses/{course_id}/materials/preview/{material_path:path}")
def preview_course_material(
    course_id: str,
    material_path: str,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        return build_material_preview(material_path, course_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/api/courses/{course_id}/materials/file/{material_path:path}")
def open_course_material(
    course_id: str,
    material_path: str,
    _owner_id: str = Depends(require_course_ownership),
) -> FileResponse:
    try:
        file_path = resolve_course_material_path(material_path, course_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(
        file_path,
        media_type=mimetypes.guess_type(file_path.name)[0] or "application/octet-stream",
        filename=file_path.name,
        content_disposition_type="inline",
    )


@router.get("/api/courses/{course_id}/materials/converted-file/{material_path:path}")
def open_converted_course_material(
    course_id: str,
    material_path: str,
    _owner_id: str = Depends(require_course_ownership),
) -> FileResponse:
    try:
        file_path = resolve_converted_material_pdf_path(material_path, course_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=f"{Path(material_path).stem}.pdf",
        content_disposition_type="inline",
    )


@router.post("/api/courses/{course_id}/materials/upload-batch")
async def upload_course_material_batch(
    course_id: str,
    request: FastAPIRequest,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        payload = await request.body()
        header_end = payload.find(b"\n")
        if header_end <= 0:
            raise ValueError("批量上传数据格式无效")
        manifest_length = int(payload[:header_end].decode("ascii"))
        manifest_start = header_end + 1
        manifest_end = manifest_start + manifest_length
        manifest = json.loads(payload[manifest_start:manifest_end].decode("utf-8"))
        if not isinstance(manifest, list):
            raise ValueError("批量上传清单格式无效")
        files: list[tuple[str, bytes]] = []
        offset = manifest_end
        for item in manifest:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("size"), int):
                raise ValueError("批量上传清单字段无效")
            next_offset = offset + item["size"]
            if next_offset > len(payload):
                raise ValueError("批量上传文件内容不完整")
            files.append((item["name"], payload[offset:next_offset]))
            offset = next_offset
        if offset != len(payload):
            raise ValueError("批量上传数据长度不匹配")
        role = str(request.query_params.get("role") or "supplementary")
        workspace = upload_course_materials(files, course_id, role=role)
        if mark_strategy_maintenance_pending(course_id, "课程资料发生变化"):
            enqueue_agent_job(course_id, "maintain_review_plan", {"event": "课程资料发生变化"})
            enqueue_agent_job(course_id, "glossary_refresh", {"event": "课程资料发生变化"}, max_attempts=2)
        return workspace
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.patch("/api/courses/{course_id}/materials/{material_path:path}/role")
async def update_generic_course_material_role(
    course_id: str,
    material_path: str,
    request: FastAPIRequest,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("资料角色请求格式无效")
        workspace = update_course_material_role(
            material_path,
            str(payload.get("role") or "supplementary"),
            course_id,
            priority_order=payload.get("priorityOrder") if payload.get("priorityOrder") is not None else None,
        )
        if mark_strategy_maintenance_pending(course_id, "资料主辅角色发生变化"):
            enqueue_agent_job(course_id, "maintain_review_plan", {"event": "资料主辅角色发生变化"})
            enqueue_agent_job(course_id, "glossary_refresh", {"event": "资料主辅角色发生变化"}, max_attempts=2)
        return workspace
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete("/api/courses/{course_id}/materials/{material_path:path}")
def delete_generic_course_material(
    course_id: str,
    material_path: str,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        workspace = delete_course_material(material_path, course_id)
        if mark_strategy_maintenance_pending(course_id, "课程资料发生变化"):
            enqueue_agent_job(course_id, "maintain_review_plan", {"event": "课程资料发生变化"})
            enqueue_agent_job(course_id, "glossary_refresh", {"event": "课程资料发生变化"}, max_attempts=2)
        return workspace
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/api/courses/{course_id}/materials/rescan")
def rescan_course_materials(
    course_id: str,
    _owner_id: str = Depends(require_course_ownership),
) -> dict[str, Any]:
    try:
        workspace = refresh_workspace_materials(course_id)
        if mark_strategy_maintenance_pending(course_id, "课程资料重新解析"):
            enqueue_agent_job(course_id, "maintain_review_plan", {"event": "课程资料重新解析"})
            enqueue_agent_job(course_id, "glossary_refresh", {"event": "课程资料重新解析"}, max_attempts=2)
        return workspace
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
