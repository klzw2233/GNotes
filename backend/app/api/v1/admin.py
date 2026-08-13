"""管理员路由：/admin/users（建用户、列表、禁用、改角色、重置密码、删除）、/admin/backup。"""
from __future__ import annotations

import logging
import secrets

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.deps import get_db_dep, require_admin
from app.core.security import hash_password
from app.repositories import backup_run_repo, user_repo
from app.schemas.auth import (
    ResetPasswordResponse,
    UserCreate,
    UserListResponse,
    UserOut,
    UserUpdate,
)
from app.schemas.common import ok
from app.services.backup_service import get_backup_status, run_backup

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _to_user_out(row: dict) -> dict:
    """把 user 行转成 UserOut 兼容 dict（is_disabled int → bool）。"""
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "role": row["role"],
        "is_disabled": bool(row.get("is_disabled", 0)),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_login_at": row.get("last_login_at"),
    }


@router.post("/users")
async def create_user(
    body: UserCreate,
    admin: dict = Depends(require_admin),
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
    user = await user_repo.get_user_by_id(db, user_id)
    return ok(_to_user_out(user), message="用户已创建")


@router.get("/users")
async def list_users(
    _admin: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db_dep),
) -> dict:
    """用户列表（不含软删除）。"""
    users = await user_repo.list_users(db)
    items = [_to_user_out(u) for u in users]
    return ok(UserListResponse(items=items, total=len(items)).model_dump())


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UserUpdate,
    admin: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db_dep),
) -> dict:
    """禁用/启用用户、修改角色。"""
    if body.is_disabled is None and body.role is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "至少需要修改一个字段")

    target = await user_repo.get_user_by_id(db, user_id)
    if not target or target.get("deleted_at"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    # 自我保护：不能禁用自己
    if body.is_disabled is True and user_id == admin["id"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能禁用自己的账户")

    # 最后管理员保护：不能把最后一个活跃管理员降级为 user 或禁用
    if (body.role == "user" or body.is_disabled is True) and target["role"] == "admin":
        if await user_repo.count_active_admins(db) <= 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能禁用或降级最后一个管理员")

    affected = await user_repo.update_user_status(
        db, user_id, is_disabled=body.is_disabled, role=body.role
    )
    if affected == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    user = await user_repo.get_user_by_id(db, user_id)
    return ok(_to_user_out(user), message="已更新")


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    admin: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db_dep),
) -> dict:
    """软删除用户（标记 deleted_at，notes 数据保留，CASCADE 不触发）。"""
    if user_id == admin["id"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删除自己")

    target = await user_repo.get_user_by_id(db, user_id)
    if not target or target.get("deleted_at"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    # 最后管理员保护
    if target["role"] == "admin" and await user_repo.count_active_admins(db) <= 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删除最后一个管理员")

    affected = await user_repo.soft_delete_user(db, user_id)
    if affected == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    return ok(message="已删除")


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    admin: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db_dep),
) -> dict:
    """重置用户密码：服务端生成随机临时密码，仅本次返回明文。"""
    target = await user_repo.get_user_by_id(db, user_id)
    if not target or target.get("deleted_at"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    temporary_password = secrets.token_urlsafe(12)  # 约 16 字符
    affected = await user_repo.update_password(
        db, user_id, hash_password(temporary_password)
    )
    if affected == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    logger.info("管理员 %s 重置了用户 %s 的密码", admin["id"], user_id)
    return ok(ResetPasswordResponse(temporary_password=temporary_password).model_dump(),
              message="密码已重置，请将临时密码安全转交用户")


@router.post("/backup")
async def trigger_backup(_admin: dict = Depends(require_admin)) -> dict:
    """手动触发备份：快照→gzip→加密→上传 Google Drive。同步返回结果。"""
    try:
        result = await run_backup()
    except Exception:
        logger.exception("手动备份失败")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "备份失败")
    return ok(result, message="备份完成")


def _next_run_at(request: Request) -> str | None:
    """从 app.state.scheduler 取下一次定时备份时间（lifespan 未触发时为 None）。"""
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        return None
    job = scheduler.get_job("daily_backup")
    if job is None or job.next_run_time is None:
        return None
    return job.next_run_time.isoformat()


@router.get("/backup")
async def backup_status(
    request: Request,
    _admin: dict = Depends(require_admin),
) -> dict:
    """查询备份配置是否齐全、最近一次备份结果、连续失败次数、下次定时备份时间。"""
    status_data = await get_backup_status()
    status_data["next_run_at"] = _next_run_at(request)
    return ok(status_data)


@router.get("/backup/runs")
async def backup_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db_dep),
) -> dict:
    """分页查询备份历史（backup_runs 表）。"""
    offset = (page - 1) * page_size
    items = await backup_run_repo.list_recent(db, limit=page_size, offset=offset)
    total = await backup_run_repo.count_all(db)
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})
