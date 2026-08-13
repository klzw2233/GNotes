"""认证路由：/auth/login、/auth/logout、/auth/change-password。"""
from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_current_user, get_db_dep
from app.core.config import get_settings
from app.core.rate_limit import login_limiter
from app.core.security import TOKEN_TTL_DAYS, create_access_token, hash_password, verify_password
from app.schemas.auth import ChangePasswordRequest, ChangePasswordResponse, LoginRequest, TokenResponse
from app.schemas.common import ok
from app.services.auth_service import login as do_login
from app.repositories import user_repo

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

    result = await do_login(db, body.username, body.password)
    if not result:
        login_limiter.record_failure(key, settings.login_window_seconds)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    token, role = result
    login_limiter.reset(key)
    return ok(
        TokenResponse(
            token=token,
            token_type="bearer",
            expires_in=TOKEN_TTL_DAYS * 86400,
            role=role,
        ).model_dump()
    )


@router.post("/logout")
async def logout(_user: dict = Depends(get_current_user)) -> dict:
    """软登出：后端无状态，仅返 200。客户端负责清 token。"""
    return ok(message="已登出")


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db_dep),
) -> dict:
    """用户修改自己密码：验证旧密码 → 更新 hash + token_version +1 → 返回新 token。

    bump version 使该用户其他设备的旧 token 失效；返回用新 ver 签发的新 token，
    前端替换后当前会话继续可用，无需重新登录。
    """
    if not verify_password(body.old_password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "旧密码错误")
    await user_repo.update_password(db, user["id"], hash_password(body.new_password))
    await user_repo.bump_token_version(db, user["id"])
    new_version = user.get("token_version", 0) + 1
    new_token = create_access_token(user["id"], user["role"], new_version)
    return ok(
        ChangePasswordResponse(token=new_token, expires_in=TOKEN_TTL_DAYS * 86400).model_dump(),
        message="密码已修改",
    )
