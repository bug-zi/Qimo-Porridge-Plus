from __future__ import annotations

from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..knowledge_service import (
    get_embedding_status,
    save_embedding_config,
    test_embedding_connection,
)
from ..study_service import (
    fetch_available_model_ids,
    get_runtime_model_api_key,
    get_runtime_model_profile,
    get_user_profile_prompt,
    save_runtime_model_profile,
    save_user_profile_prompt,
)

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


@router.get("/api/user-profile")
def user_profile_prompt() -> dict[str, str]:
    return get_user_profile_prompt()


@router.put("/api/user-profile")
def update_user_profile_prompt(payload: UserProfilePromptUpdateRequest) -> dict[str, str]:
    try:
        return save_user_profile_prompt(payload.content)
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
