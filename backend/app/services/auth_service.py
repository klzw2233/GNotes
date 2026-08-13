"""认证业务编排：登录 + 初始管理员 bootstrap。"""
from __future__ import annotations

import logging

import aiosqlite

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.repositories import user_repo

logger = logging.getLogger(__name__)


async def login(db: aiosqlite.Connection, username: str, password: str) -> tuple[str, str] | None:
    """登录成功返回 (JWT, role)，失败返回 None。

    被禁用用户返回 None（与密码错误同样 401，不暴露「账户存在但被禁用」）。
    """
    user = await user_repo.get_user_by_username(db, username)
    if not user:
        return None
    if user.get("is_disabled"):
        return None  # 禁用账户：登录失败（与凭据错误同样处理，避免信息泄露）
    if not verify_password(password, user["password_hash"]):
        return None
    await user_repo.update_last_login(db, user["id"])
    return create_access_token(user["id"], user["role"]), user["role"]


async def bootstrap_admin(db: aiosqlite.Connection) -> None:
    """若 users 表为空，用 .env 配置的凭据创建初始管理员。已有用户则跳过。"""
    settings = get_settings()
    if await user_repo.count_users(db) > 0:
        logger.info("users 表已有用户，跳过管理员 bootstrap")
        return

    if not settings.initial_admin_password:
        logger.warning("INITIAL_ADMIN_PASSWORD 未设置，无法创建初始管理员")
        return

    password_hash = hash_password(settings.initial_admin_password)
    await user_repo.create_user(
        db,
        username=settings.initial_admin_username,
        email=settings.initial_admin_email,
        password_hash=password_hash,
        role="admin",
    )
    logger.info(
        "已创建初始管理员: username=%s email=%s",
        settings.initial_admin_username,
        settings.initial_admin_email,
    )
