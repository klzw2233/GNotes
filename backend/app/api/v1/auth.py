"""认证路由：/auth/login、/auth/logout。"""
from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_db_dep
from app.core.security import TOKEN_TTL_DAYS
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.common import ok
from app.services.auth_service import login as do_login

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(
    body: LoginRequest,
    db: aiosqlite.Connection = Depends(get_db_dep),
) -> dict:
    """用户名+密码 → JWT。"""
    token = await do_login(db, body.username, body.password)
    if not token:
        return {"code": 401, "message": "用户名或密码错误", "data": None}
    return ok(
        TokenResponse(
            token=token, token_type="bearer", expires_in=TOKEN_TTL_DAYS * 86400
        ).model_dump()
    )


@router.post("/logout")
async def logout(_user: dict = Depends(get_current_user)) -> dict:
    """软登出：后端无状态，仅返 200。客户端负责清 token。"""
    return ok(message="已登出")
