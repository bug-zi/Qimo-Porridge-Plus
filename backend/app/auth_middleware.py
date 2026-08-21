"""白名单式认证中间件（阶段1）。

默认拒绝：所有 /api/* 请求必须携带有效 Bearer access token；
仅 AUTH_WHITELIST 中的路径前缀/精确匹配放行（含 /api/auth/* 自身）。

验证通过后把 user_id 写入 request.state.user_id，供后续阶段2多租户
（contextvars owner_id 穿透）直接取用。文档路由（/docs、/openapi.json）
与非 /api 路径不拦截。
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from .auth_service import decode_access_token

# 无需登录即可访问的路径（精确匹配）。/api/auth/me 与 /api/auth/logout
# 不在白名单——它们需要 user_id，必须走 token 验证。
AUTH_WHITELIST_EXACT: frozenset[str] = frozenset(
    {
        "/api/health",
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/refresh",
    }
)


def is_path_whitelisted(path: str) -> bool:
    return path in AUTH_WHITELIST_EXACT


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if not path.startswith("/api/") or is_path_whitelisted(path):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "未登录或缺少访问令牌"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = auth_header[len("Bearer "):].strip()
        payload = decode_access_token(token)
        if payload is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "访问令牌无效或已过期"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # user_id 供后续多租户隔离（阶段2）取用：request.state.user_id / Depends(current_user_id)
        request.state.user_id = payload["sub"]
        return await call_next(request)
