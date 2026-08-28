"""资料管理域（阶段2-3 从 study_service.py 抽取）。

职责：课程资料库的扫描/上传/删除、主辅角色管理、资料记忆
（materialMemory/digest）、知识库同步入口。

依赖方向：materials → material_parser / knowledge_service / paths，
禁止模块级 import study_service（成环）；load_workspace / save_workspace /
_course_material_directory / _workspace_is_planned / _ensure_workspace_content_quality /
_clear_pre_plan_content 属于 workspace 域（留在 study_service），
本模块在函数体内延迟 import——调用时读取 study_service 命名空间，
测试 patch study_service.load_workspace / scan_course_materials 等依旧生效
（course_feedback_service.py 的既有惯例）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .knowledge_service import (
    get_knowledge_status,
    import_workspace_messages,
    sync_material_documents,
)
from .material_parser import (
    MATERIAL_ANALYSIS_VERSION,
    _extract_material_content,
    _relative_material_path,
    analyze_course_material,
    resolve_course_material_path,
)

# 资料上传大小上限（字节）。默认单文件 512MB、单次批量 1GB；可用环境变量
# MAX_SINGLE_MATERIAL_MB / MAX_BATCH_MATERIAL_MB 覆盖（单位 MB）。
import os

MAX_SINGLE_MATERIAL_BYTES = int(os.getenv("MAX_SINGLE_MATERIAL_MB", "512")) * 1024 * 1024
MAX_BATCH_MATERIAL_BYTES = int(os.getenv("MAX_BATCH_MATERIAL_MB", "1024")) * 1024 * 1024

MATERIAL_ROLE_PRIMARY = "primary"
MATERIAL_ROLE_SUPPLEMENTARY = "supplementary"
MATERIAL_ROLE_VALUES = {MATERIAL_ROLE_PRIMARY, MATERIAL_ROLE_SUPPLEMENTARY}


def _normalize_material_role(value: Any) -> str:
    role = str(value or MATERIAL_ROLE_SUPPLEMENTARY).strip().lower()
    return role if role in MATERIAL_ROLE_VALUES else MATERIAL_ROLE_SUPPLEMENTARY


def _material_role_metadata(workspace: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = workspace.get("materialRoles")
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for path, config in raw.items():
        if not isinstance(config, dict):
            continue
        role = _normalize_material_role(config.get("role"))
        try:
            priority_order = int(config.get("priorityOrder") or 0)
        except (TypeError, ValueError):
            priority_order = 0
        normalized[str(path)] = {"role": role, "priorityOrder": max(0, priority_order)}
    return normalized


def _apply_material_roles(materials: list[dict[str, Any]], workspace: dict[str, Any]) -> None:
    roles = _material_role_metadata(workspace)
    for index, material in enumerate(materials, start=1):
        relative_path = str(material.get("relativePath", ""))
        config = roles.get(relative_path, {})
        role = _normalize_material_role(config.get("role"))
        priority_order = int(config.get("priorityOrder") or 0) or index
        material["role"] = role
        material["isPrimary"] = role == MATERIAL_ROLE_PRIMARY
        material["priorityOrder"] = priority_order
    workspace["materialRoles"] = {
        str(material.get("relativePath")): {
            "role": str(material.get("role") or MATERIAL_ROLE_SUPPLEMENTARY),
            "priorityOrder": int(material.get("priorityOrder") or 0),
        }
        for material in materials
        if isinstance(material, dict) and material.get("relativePath")
    }


def scan_course_materials(
    course_id: str,
    *,
    force_reparse: bool = False,
    workspace: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from .study_service import _course_material_directory

    course_directory = _course_material_directory(course_id)
    if not course_directory.exists():
        return []

    materials: list[dict[str, Any]] = []
    for file_path in sorted(path for path in course_directory.rglob("*") if path.is_file()):
        if file_path.name == "AGENTS.md":
            continue
        suffix = file_path.suffix.lower().lstrip(".")
        material: dict[str, Any] = {
            "name": file_path.name,
            "relativePath": _relative_material_path(file_path, course_id),
            "type": suffix.upper() if suffix else "FILE",
            "size": file_path.stat().st_size,
            "detail": "已收录，待引用",
        }
        material.update(analyze_course_material(file_path, force_reparse=force_reparse))
        materials.append(material)
    if workspace is not None:
        _apply_material_roles(materials, workspace)
    return materials


def _material_digest(materials: list[dict[str, Any]]) -> str:
    digest_payload = [
        {
            "path": item.get("relativePath", ""),
            "size": item.get("size", 0),
            "aiStatus": item.get("aiStatus", ""),
            "analysisVersion": item.get("analysisVersion", 0),
            "role": item.get("role", MATERIAL_ROLE_SUPPLEMENTARY),
            "priorityOrder": item.get("priorityOrder", 0),
        }
        for item in materials
    ]
    raw = json.dumps(digest_payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _build_material_memory(
    materials: list[dict[str, Any]],
    *,
    previous_digest: str = "",
    change_note: str | None = None,
) -> dict[str, Any]:
    digest = _material_digest(materials)
    readable = [item for item in materials if item.get("aiReadable")]
    primary = [item for item in materials if item.get("role") == MATERIAL_ROLE_PRIMARY]
    supplementary = [item for item in materials if item.get("role") != MATERIAL_ROLE_PRIMARY]
    partial = [item for item in materials if item.get("aiStatus") == "partial"]
    unreadable = [item for item in materials if item.get("aiStatus") == "unreadable"]
    skipped = [item for item in materials if item.get("aiStatus") == "skipped"]
    changed = bool(change_note) or (bool(previous_digest) and previous_digest != digest)
    return {
        "digest": digest,
        "sourceCount": len(materials),
        "aiReadableCount": len(readable),
        "aiPartialCount": len(partial),
        "aiSkippedCount": len(skipped),
        "aiUnreadableCount": len(unreadable),
        "primaryCount": len(primary),
        "supplementaryCount": len(supplementary),
        "primaryMaterials": [str(item.get("relativePath") or item.get("name")) for item in primary],
        "lastChange": change_note or "资料库已重新解析",
        "lastSyncedAt": datetime.now().isoformat(timespec="seconds"),
        "contentRefreshRecommended": changed,
        "summary": (
            f"当前资料库共 {len(materials)} 份资料，"
            f"其中 {len(primary)} 份主资料、{len(supplementary)} 份辅资料；"
            f"{len(readable)} 份可进入 AI 上下文，"
            f"{len(partial)} 份部分解析，{len(unreadable)} 份未解析。"
        ),
    }


def _mark_material_memory(
    workspace: dict[str, Any],
    materials: list[dict[str, Any]],
    *,
    change_note: str | None = None,
) -> None:
    _apply_material_roles(materials, workspace)
    previous_digest = str(workspace.get("materialMemory", {}).get("digest", ""))
    material_memory = _build_material_memory(
        materials,
        previous_digest=previous_digest,
        change_note=change_note,
    )
    workspace["materialMemory"] = material_memory
    workspace["materials"] = materials
    workspace["materialAnalysisRefreshedAt"] = material_memory["lastSyncedAt"]
    if material_memory["contentRefreshRecommended"]:
        workspace["diagnostic"] = {
            "estimatedScore": workspace.get("diagnostic", {}).get("estimatedScore", "未摸底"),
            "message": "资料库已变更，AI 已更新资料记忆；当前复习主线和模拟卷建议根据最新资料重新审阅。",
        }


def sync_course_knowledge(
    course_id: str,
    workspace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .study_service import load_workspace, save_workspace

    should_save_workspace = workspace is None
    current_workspace = workspace or load_workspace(course_id, refresh_materials=False)
    _apply_material_roles(current_workspace.get("materials", []), current_workspace)
    documents: list[dict[str, str]] = []
    for material in current_workspace.get("materials", []):
        if not isinstance(material, dict):
            continue
        relative_path = str(material.get("relativePath", ""))
        if not relative_path:
            continue
        try:
            file_path = resolve_course_material_path(relative_path, course_id)
            parsed = _extract_material_content(file_path)
            text = str(parsed.get("text") or material.get("excerpt") or "")
        except (FileNotFoundError, OSError):
            text = str(material.get("excerpt") or "")
        documents.append(
            {
                "relativePath": relative_path,
                "name": str(material.get("name") or Path(relative_path).name),
                "text": text,
                "role": str(material.get("role") or MATERIAL_ROLE_SUPPLEMENTARY),
                "priorityOrder": int(material.get("priorityOrder") or 0),
            }
        )

    sync_result = sync_material_documents(course_id, documents)
    import_workspace_messages(course_id, current_workspace.get("messages", []))
    status = get_knowledge_status(course_id)
    status["lastSyncedAt"] = datetime.now().isoformat(timespec="seconds")
    status["changedMaterials"] = sync_result["changed"]
    current_workspace["knowledgeBase"] = status
    if should_save_workspace:
        save_workspace(current_workspace, course_id)
    return status


def _safe_upload_material_name(filename: str) -> str:
    normalized = filename.strip().replace("\\", "/").split("/")[-1]
    if not normalized or normalized in {".", ".."} or normalized.lower() == "agents.md":
        raise ValueError("资料文件名无效")
    if any(char in normalized for char in '<>:"/\\|?*'):
        raise ValueError("资料文件名不能包含路径或特殊字符")
    return normalized


def upload_course_material(filename: str, content: bytes, course_id: str) -> dict[str, Any]:
    from .study_service import _course_material_directory

    safe_name = _safe_upload_material_name(filename)
    if not content:
        raise ValueError("不能导入空文件")
    if len(content) > MAX_SINGLE_MATERIAL_BYTES:
        raise ValueError(f"单个资料文件不能超过 {MAX_SINGLE_MATERIAL_BYTES // (1024 * 1024)}MB")

    course_directory = _course_material_directory(course_id)
    course_directory.mkdir(parents=True, exist_ok=True)
    target_path = course_directory / safe_name
    if target_path.exists():
        stem = target_path.stem
        suffix = target_path.suffix
        counter = 2
        while target_path.exists():
            target_path = course_directory / f"{stem}-{counter}{suffix}"
            counter += 1
    target_path.write_bytes(content)
    return refresh_workspace_materials(course_id, change_note=f"导入资料：{target_path.name}")


def upload_course_materials(
    files: list[tuple[str, bytes]],
    course_id: str,
    *,
    role: str = MATERIAL_ROLE_SUPPLEMENTARY,
) -> dict[str, Any]:
    from .study_service import _course_material_directory, load_workspace, save_workspace

    if not files:
        raise ValueError("没有可导入的资料文件")
    total_size = sum(len(content) for _, content in files)
    if total_size > MAX_BATCH_MATERIAL_BYTES:
        raise ValueError(f"单次批量导入不能超过 {MAX_BATCH_MATERIAL_BYTES // (1024 * 1024)}MB")

    course_directory = _course_material_directory(course_id)
    course_directory.mkdir(parents=True, exist_ok=True)
    saved_names: list[str] = []
    for filename, content in files:
        safe_name = _safe_upload_material_name(filename)
        if not content:
            raise ValueError(f"{safe_name} 是空文件，不能导入")
        if len(content) > MAX_SINGLE_MATERIAL_BYTES:
            raise ValueError(f"{safe_name} 超过 {MAX_SINGLE_MATERIAL_BYTES // (1024 * 1024)}MB，不能导入")

        target_path = course_directory / safe_name
        if target_path.exists():
            stem = target_path.stem
            suffix = target_path.suffix
            counter = 2
            while target_path.exists():
                target_path = course_directory / f"{stem}-{counter}{suffix}"
                counter += 1
        target_path.write_bytes(content)
        saved_names.append(target_path.name)

    normalized_role = _normalize_material_role(role)
    workspace = load_workspace(course_id, refresh_materials=False)
    roles = _material_role_metadata(workspace)
    for index, saved_name in enumerate(saved_names, start=1):
        roles[saved_name] = {"role": normalized_role, "priorityOrder": len(roles) + index}
    workspace["materialRoles"] = roles
    preview_names = "、".join(saved_names[:3])
    suffix = "等" if len(saved_names) > 3 else ""
    role_label = "主资料" if normalized_role == MATERIAL_ROLE_PRIMARY else "辅资料"
    _mark_material_memory(
        workspace,
        scan_course_materials(course_id, workspace=workspace),
        change_note=f"批量导入{role_label}：{preview_names}{suffix}，共 {len(saved_names)} 份",
    )
    try:
        sync_course_knowledge(course_id, workspace)
    except Exception as error:
        workspace["knowledgeBase"] = {"status": "unavailable", "message": f"知识库索引更新失败：{error}"}
    save_workspace(workspace, course_id)
    return workspace


def delete_course_material(relative_path: str, course_id: str) -> dict[str, Any]:
    file_path = resolve_course_material_path(relative_path, course_id)
    deleted_name = _relative_material_path(file_path, course_id)
    file_path.unlink()
    return refresh_workspace_materials(course_id, change_note=f"删除资料：{deleted_name}")


def _workspace_needs_material_refresh(workspace: dict[str, Any]) -> bool:
    materials = workspace.get("materials")
    if not isinstance(materials, list):
        return True
    return any(
        not isinstance(item, dict) or item.get("analysisVersion") != MATERIAL_ANALYSIS_VERSION
        for item in materials
    )


def update_course_material_role(
    relative_path: str,
    role: str,
    course_id: str,
    *,
    priority_order: int | None = None,
) -> dict[str, Any]:
    from .study_service import load_workspace, save_workspace

    normalized_role = _normalize_material_role(role)
    workspace = load_workspace(course_id, refresh_materials=False)
    materials = scan_course_materials(course_id, workspace=workspace)
    if not any(str(item.get("relativePath")) == relative_path for item in materials):
        raise FileNotFoundError(f"资料不存在：{relative_path}")
    roles = _material_role_metadata(workspace)
    if priority_order is None:
        existing_order = roles.get(relative_path, {}).get("priorityOrder")
        priority_order = int(existing_order or 0) or next(
            (index for index, item in enumerate(materials, start=1) if str(item.get("relativePath")) == relative_path),
            1,
        )
    roles[relative_path] = {"role": normalized_role, "priorityOrder": max(0, int(priority_order or 0))}
    workspace["materialRoles"] = roles
    _mark_material_memory(
        workspace,
        scan_course_materials(course_id, workspace=workspace),
        change_note="资料主辅角色已更新",
    )
    try:
        sync_course_knowledge(course_id, workspace)
    except Exception as error:
        workspace["knowledgeBase"] = {"status": "unavailable", "message": f"知识库索引更新失败：{error}"}
    save_workspace(workspace, course_id)
    return workspace


def refresh_workspace_materials(
    course_id: str,
    *,
    change_note: str | None = None,
    force_reparse: bool = False,
) -> dict[str, Any]:
    # _workspace_is_planned / _ensure_workspace_content_quality / _clear_pre_plan_content
    # 属 workspace 域（study_service），延迟 import 保持打桩面不变。
    from .study_service import (
        _clear_pre_plan_content,
        _ensure_workspace_content_quality,
        _workspace_is_planned,
        load_workspace,
        save_workspace,
    )

    workspace = load_workspace(course_id, refresh_materials=False)
    _mark_material_memory(
        workspace,
        scan_course_materials(course_id, force_reparse=force_reparse, workspace=workspace),
        change_note=change_note,
    )
    if _workspace_is_planned(workspace):
        _ensure_workspace_content_quality(workspace)
    else:
        _clear_pre_plan_content(workspace)
    try:
        sync_course_knowledge(course_id, workspace)
    except Exception as error:
        workspace["knowledgeBase"] = {
            "status": "unavailable",
            "message": f"知识库索引更新失败：{error}",
        }
    save_workspace(workspace, course_id)
    return workspace
