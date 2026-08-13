"""认证路由：/auth/login、/auth/logout。"""
from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_current_user, get_db_dep
from app.core.config import get_settings
from app.core.rate_limit import login_limiter
from app.core.security import TOKEN_TTL_DAYS
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.common import ok
from app.services.auth_service import login as do_login

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    db: aiosqlite.Connection = Depends(get_db_dep),
) -> dict:
    """用户名+密码 → JWT。失败按 IP 限流。"""
    settings = get_settings()
    key = _client_key(request)
    if login_limiter.is_blocked(key, settings.login_max_attempts, settings.login_window_seconds):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "登录尝试过多，请稍后再试")

    token = await do_login(db, body.username, body.password)
    if not token:
        login_limiter.record_failure(key, settings.login_window_seconds)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    login_limiter.reset(key)
    return ok(
        TokenResponse(
            token=token, token_type="bearer", expires_in=TOKEN_TTL_DAYS * 86400
        ).model_dump()
    )


@router.post("/logout")
async def logout(_user: dict = Depends(get_current_user)) -> dict:
    """软登出：后端无状态，仅返 200。客户端负责清 token。"""
    return ok(message="已登出")
