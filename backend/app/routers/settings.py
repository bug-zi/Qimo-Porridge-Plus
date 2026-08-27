from __future__ import annotations

from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ..knowledge_service import (
    get_embedding_status,
    save_embedding_config,
    test_embedding_connection,
)
from ..auth_service import (
    delete_account_avatar,
    get_account_profile,
    save_account_avatar,
    update_account_profile,
)
from ..study_service import (
    fetch_available_model_ids,
    probe_model_chat,
    resolve_api_key_for_base_url,
    get_backup_model_profile,
    get_model_profiles,
    get_runtime_model_api_key,
    get_runtime_model_profile,
    get_user_profile_prompt,
    save_backup_model_profile,
    save_model_profile,
    save_runtime_model_profile,
    save_user_profile_prompt,
)
from .deps import current_owner_id

router = APIRouter()


class ModelProfileTestRequest(BaseModel):
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=200)


class ModelProfileTestResponse(BaseModel):
    success: bool
    message: str
    available_models: list[str] = Field(default_factory=list)


class RuntimeModelUpdateRequest(BaseModel):
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str = Field(default="", max_length=500)
    model: str = Field(min_length=1, max_length=200)


class UserProfilePromptUpdateRequest(BaseModel):
    content: str = Field(default="", max_length=4000)


class AccountProfileUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=40)
    gender: str = Field(default="", max_length=20)
    age: int | None = Field(default=None, ge=0, le=150)
    signature: str = Field(default="", max_length=200)


class EmbeddingConfigRequest(BaseModel):
    enabled: bool = True
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=200)


class ModelProfileEntryRequest(BaseModel):
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str = Field(default="", max_length=500)
    model: str = Field(min_length=1, max_length=200)


class BackupModelUpdateRequest(BaseModel):
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str = Field(default="", max_length=500)
    model: str = Field(min_length=1, max_length=200)


@router.post("/api/model-profiles/test", response_model=ModelProfileTestResponse)
def test_model_profile(payload: ModelProfileTestRequest) -> ModelProfileTestResponse:
    base_url = payload.base_url.strip().rstrip("/")
    parsed_url = urlparse(base_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        raise HTTPException(status_code=422, detail="Base URL 必须是合法的 HTTP 或 HTTPS 地址")

    # key 留空表示沿用已保存的：按被测服务的 base_url 匹配主模型/备用/档案中
    # 已保存的 key，而不是一律取主模型的 key（跨服务商会产生误导性 401）。
    api_key = resolve_api_key_for_base_url(base_url, payload.api_key)
    if not api_key:
        return ModelProfileTestResponse(success=False, message="未找到该服务已保存的 API Key，请先填写")

    try:
        available_models = fetch_available_model_ids(base_url, api_key)
    except HTTPError as error:
        return ModelProfileTestResponse(success=False, message=f"模型服务返回 HTTP {error.code}，请检查 API Key 和服务地址")
    except URLError:
        return ModelProfileTestResponse(success=False, message="无法连接模型服务，请检查 Base URL、网络或本地代理")
    except TimeoutError:
        return ModelProfileTestResponse(success=False, message="连接超时，请检查服务是否可用")
    except ValueError:
        return ModelProfileTestResponse(success=False, message="模型服务返回内容无法解析，请确认 /models 接口兼容 OpenAI 格式")

    selected_model = payload.model.strip()
    if selected_model and available_models and selected_model not in available_models:
        return ModelProfileTestResponse(
            success=False,
            message=f"服务可达（{len(available_models)} 个模型），但「{selected_model}」不在可用列表中",
            available_models=available_models,
        )

    # 关键：/models 不消耗额度，账户无套餐时也会成功——必须真实对话一次才能确认可用。
    probe_model = selected_model or (available_models[0] if available_models else "")
    if not probe_model:
        return ModelProfileTestResponse(
            success=False,
            message="服务可达，但未读取到模型列表且未填写模型名，无法完成实测",
            available_models=available_models,
        )
    probe = probe_model_chat(base_url, api_key, probe_model)
    model_count = len(available_models)
    if not probe["success"]:
        return ModelProfileTestResponse(
            success=False,
            message=f"服务可达（{model_count} 个模型），但实测调用失败：{probe['message']}",
            available_models=available_models,
        )
    return ModelProfileTestResponse(
        success=True,
        message=f"连接成功且模型实测可用（{model_count} 个模型）" if model_count else probe["message"],
        available_models=available_models,
    )


@router.get("/api/runtime-model")
def runtime_model() -> dict[str, str | bool | list[str]]:
    return get_runtime_model_profile()


@router.get("/api/model-profiles")
def model_profiles() -> dict[str, Any]:
    return get_model_profiles()


@router.put("/api/model-profiles/{profile_id}")
def update_model_profile(profile_id: str, payload: ModelProfileEntryRequest) -> dict[str, Any]:
    base_url = payload.base_url.strip().rstrip("/")
    parsed_url = urlparse(base_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        raise HTTPException(status_code=422, detail="Base URL 必须是合法的 HTTP 或 HTTPS 地址")
    return save_model_profile(profile_id, base_url, payload.api_key, payload.model)


@router.get("/api/backup-model")
def backup_model() -> dict[str, Any]:
    return get_backup_model_profile()


@router.put("/api/backup-model")
def update_backup_model(payload: BackupModelUpdateRequest) -> dict[str, Any]:
    base_url = payload.base_url.strip().rstrip("/")
    parsed_url = urlparse(base_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        raise HTTPException(status_code=422, detail="Base URL 必须是合法的 HTTP 或 HTTPS 地址")
    return save_backup_model_profile(base_url, payload.api_key, payload.model)


@router.put("/api/runtime-model")
def update_runtime_model(payload: RuntimeModelUpdateRequest) -> dict[str, str | bool | list[str]]:
    base_url = payload.base_url.strip().rstrip("/")
    parsed_url = urlparse(base_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        raise HTTPException(status_code=422, detail="Base URL 必须是合法的 HTTP 或 HTTPS 地址")
    if not payload.api_key.strip() and not get_runtime_model_api_key():
        raise HTTPException(status_code=422, detail="请先填写 API Key")
    return save_runtime_model_profile(base_url, payload.api_key, payload.model)


@router.get("/api/account-profile")
def account_profile(owner_id: str = Depends(current_owner_id)) -> dict[str, Any]:
    profile = get_account_profile(owner_id)
    if profile is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return profile


@router.put("/api/account-profile")
def update_account_profile_route(
    payload: AccountProfileUpdateRequest,
    owner_id: str = Depends(current_owner_id),
) -> dict[str, Any]:
    try:
        profile = update_account_profile(
            owner_id,
            display_name=payload.display_name,
            gender=payload.gender,
            age=payload.age,
            signature=payload.signature,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if profile is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return profile


AVATAR_MAX_BYTES = 2 * 1024 * 1024
AVATAR_MIME_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
}


@router.post("/api/account-profile/avatar")
async def upload_account_avatar(
    avatar: UploadFile = File(...),
    owner_id: str = Depends(current_owner_id),
) -> dict[str, Any]:
    mime_type = (avatar.content_type or "").lower()
    signatures = AVATAR_MIME_SIGNATURES.get(mime_type)
    if signatures is None:
        raise HTTPException(status_code=422, detail="仅支持 JPG、PNG、GIF 或 WebP 图片")
    image_data = await avatar.read(AVATAR_MAX_BYTES + 1)
    await avatar.close()
    if not image_data:
        raise HTTPException(status_code=422, detail="请选择非空图片文件")
    if len(image_data) > AVATAR_MAX_BYTES:
        raise HTTPException(status_code=413, detail="头像图片不能超过 2 MB")
    if not any(image_data.startswith(signature) for signature in signatures):
        raise HTTPException(status_code=422, detail="图片文件内容与格式不符")
    if mime_type == "image/webp" and (len(image_data) < 12 or image_data[8:12] != b"WEBP"):
        raise HTTPException(status_code=422, detail="图片文件内容与格式不符")
    profile = save_account_avatar(owner_id, image_data, mime_type)
    if profile is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return profile


@router.delete("/api/account-profile/avatar")
def remove_account_avatar(owner_id: str = Depends(current_owner_id)) -> dict[str, Any]:
    profile = delete_account_avatar(owner_id)
    if profile is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return profile


@router.get("/api/user-profile")
def user_profile_prompt(owner_id: str = Depends(current_owner_id)) -> dict[str, str]:
    # 阶段2多租户：自画像按用户分键存储，A 的画像不再注入 B 的 AI 对话
    return get_user_profile_prompt(owner_id)


@router.put("/api/user-profile")
def update_user_profile_prompt(
    payload: UserProfilePromptUpdateRequest,
    owner_id: str = Depends(current_owner_id),
) -> dict[str, str]:
    try:
        return save_user_profile_prompt(payload.content, owner_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/api/knowledge/embedding")
def embedding_status() -> dict[str, Any]:
    return get_embedding_status()


@router.put("/api/knowledge/embedding")
def update_embedding_config(payload: EmbeddingConfigRequest) -> dict[str, Any]:
    try:
        return save_embedding_config({"enabled": payload.enabled, "baseUrl": payload.base_url, "model": payload.model})
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/api/knowledge/embedding/test")
def test_saved_embedding() -> dict[str, Any]:
    return test_embedding_connection()
