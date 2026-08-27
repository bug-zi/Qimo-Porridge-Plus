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
    get_runtime_model_api_key,
    get_runtime_model_profile,
    get_user_profile_prompt,
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


@router.post("/api/model-profiles/test", response_model=ModelProfileTestResponse)
def test_model_profile(payload: ModelProfileTestRequest) -> ModelProfileTestResponse:
    base_url = payload.base_url.strip().rstrip("/")
    parsed_url = urlparse(base_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        raise HTTPException(status_code=422, detail="Base URL 必须是合法的 HTTP 或 HTTPS 地址")

    api_key = payload.api_key.strip() or get_runtime_model_api_key()
    if not api_key:
        return ModelProfileTestResponse(success=False, message="请先填写 API Key 或保存本机 API Key")

    try:
        available_models = fetch_available_model_ids(base_url, api_key)
        selected_model = payload.model.strip()
        if selected_model and available_models and selected_model not in available_models:
            return ModelProfileTestResponse(
                success=False,
                message="连接成功，但当前模型不在可用列表中",
                available_models=available_models,
            )
        model_count = len(available_models)
        message = f"连接成功，已读取 {model_count} 个可用模型" if model_count else "连接成功，但未读取到可用模型列表"
        return ModelProfileTestResponse(success=True, message=message, available_models=available_models)
    except HTTPError as error:
        return ModelProfileTestResponse(success=False, message=f"模型服务返回 HTTP {error.code}，请检查 API Key 和服务地址")
    except URLError:
        return ModelProfileTestResponse(success=False, message="无法连接模型服务，请检查 Base URL、网络或本地代理")
    except TimeoutError:
        return ModelProfileTestResponse(success=False, message="连接超时，请检查服务是否可用")
    except ValueError:
        return ModelProfileTestResponse(success=False, message="模型服务返回内容无法解析，请确认 /models 接口兼容 OpenAI 格式")


@router.get("/api/runtime-model")
def runtime_model() -> dict[str, str | bool | list[str]]:
    return get_runtime_model_profile()


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
