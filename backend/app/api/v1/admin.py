"""管理员路由：/admin/users（建用户）、/admin/backup（手动备份）。"""
from __future__ import annotations

import logging

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_db_dep, require_admin
from app.core.security import hash_password
from app.repositories import user_repo
from app.schemas.auth import UserCreate
from app.schemas.common import ok
from app.services.backup_service import get_backup_status, run_backup

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/users")
async def create_user(
    body: UserCreate,
    _admin: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db_dep),
) -> dict:
    """管理员创建普通用户。"""
    if await user_repo.get_user_by_username(db, body.username):
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")
    if await user_repo.get_user_by_email(db, body.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "邮箱已存在")
    user_id = await user_repo.create_user(
        db,
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role="user",
    )
    return ok(
        {"id": user_id, "username": body.username, "email": body.email, "role": "user"},
        message="用户已创建",
    )


@router.post("/backup")
async def trigger_backup(_admin: dict = Depends(require_admin)) -> dict:
    """手动触发备份：快照→gzip→加密→上传 Google Drive。同步返回结果。"""
    try:
        result = await run_backup()
    except Exception:
        logger.exception("手动备份失败")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "备份失败")
    return ok(result, message="备份完成")


@router.get("/backup")
async def backup_status(_admin: dict = Depends(require_admin)) -> dict:
    """查询备份配置是否齐全，以及最近一次备份结果。"""
    return ok(get_backup_status())
