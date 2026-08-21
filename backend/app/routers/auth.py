"""认证路由（阶段1）：注册 / 登录 / 刷新 / 登出 / 当前用户信息。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from ..auth_service import (
    authenticate_user,
    get_user_by_id,
    issue_token_pair,
    register_user,
    revoke_all_refresh_tokens,
    rotate_refresh_token,
)

router = APIRouter()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(default="", max_length=40)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=256)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(default="", max_length=256)


@router.post("/api/auth/register")
def register(payload: RegisterRequest) -> dict[str, object]:
    try:
        user = register_user(payload.email, payload.password, payload.display_name)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    # 注册即登录：直接发 token 对
    user_with_profile = {**user, "display_name": payload.display_name.strip() or payload.email, "role": "user"}
    return issue_token_pair(user_with_profile)


@router.post("/api/auth/login")
def login(payload: LoginRequest) -> dict[str, object]:
    user = authenticate_user(payload.email, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="邮箱或密码不正确")
    return issue_token_pair(user)


@router.post("/api/auth/refresh")
def refresh(payload: RefreshRequest) -> dict[str, object]:
    rotated = rotate_refresh_token(payload.refresh_token)
    if rotated is None:
        # refresh token 无效/过期/被吊销重放：前端应跳回登录页
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    user, _new_token = rotated
    return issue_token_pair(user)


@router.post("/api/auth/logout")
def logout(payload: LogoutRequest, request: Request) -> dict[str, str]:
    # 登出只吊销 refresh token；access token 最多再活 30 分钟（无状态，无法提前作废）
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        revoke_all_refresh_tokens(user_id)
    return {"status": "ok"}


@router.get("/api/auth/me")
def me(request: Request) -> dict[str, str]:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user
