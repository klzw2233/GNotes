"""FastAPI 依赖：get_db / get_current_user / require_admin。"""
from __future__ import annotations

from collections.abc import AsyncIterator

import aiosqlite
import jwt
from fastapi import Depends, Header, HTTPException, status

from app.core.security import decode_access_token
from app.db.connection import get_db
from app.repositories import user_repo


async def get_db_dep() -> AsyncIterator[aiosqlite.Connection]:
    async with get_db() as db:
        yield db


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: aiosqlite.Connection = Depends(get_db_dep),
) -> dict:
    """解析 Bearer JWT → 查库得到 user。失败 401。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少认证令牌")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌已过期")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌无效")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌无效")

    user = await user_repo.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    # 禁用/软删除即时生效：旧 JWT 在下次请求时即失效（无需等过期）
    if user.get("is_disabled"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账户已被禁用")
    if user.get("deleted_at"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账户已删除")
    # token 版本号比对：改密/重置密码后旧 JWT 失效（payload.get 兼容无 ver 的旧 token → 0）
    token_ver = payload.get("ver", 0)
    if token_ver != user.get("token_version", 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌已失效，请重新登录")
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """要求当前用户为管理员。失败 403。"""
    if user.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user
