"""users 表数据访问层。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import aiosqlite


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_user(
    db: aiosqlite.Connection,
    *,
    username: str,
    email: str,
    password_hash: str,
    role: str = "user",
) -> str:
    user_id = str(uuid.uuid4())
    now = _now_iso()
    await db.execute(
        """INSERT INTO users (id, username, email, password_hash, role, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, username, email, password_hash, role, now, now),
    )
    await db.commit()
    return user_id


async def get_user_by_username(db: aiosqlite.Connection, username: str) -> dict | None:
    """按 username 查用户（排除软删除）。软删除用户视为不存在，不可登录、不可同名重建。"""
    cur = await db.execute(
        "SELECT * FROM users WHERE username = ? AND deleted_at IS NULL",
        (username,),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def get_user_by_email(db: aiosqlite.Connection, email: str) -> dict | None:
    cur = await db.execute(
        "SELECT * FROM users WHERE email = ? AND deleted_at IS NULL",
        (email,),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def get_user_by_id(db: aiosqlite.Connection, user_id: str) -> dict | None:
    """按 id 查用户（含软删除）。

    不加 deleted_at 过滤：get_current_user 需要能查到软删除用户以判定是否已删除
    （软删除用户 token 下次请求应 401）。admin 查看历史也需可见。
    """
    cur = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def count_users(db: aiosqlite.Connection) -> int:
    cur = await db.execute("SELECT COUNT(*) FROM users WHERE deleted_at IS NULL")
    row = await cur.fetchone()
    return row[0] if row else 0


async def list_users(db: aiosqlite.Connection, *, include_deleted: bool = False) -> list[dict]:
    """用户列表。默认不含软删除。"""
    sql = "SELECT * FROM users"
    if not include_deleted:
        sql += " WHERE deleted_at IS NULL"
    sql += " ORDER BY created_at ASC"
    cur = await db.execute(sql)
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def count_active_admins(db: aiosqlite.Connection) -> int:
    """未禁用、未软删除的管理员数量（用于「最后管理员」保护）。"""
    cur = await db.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_disabled = 0 AND deleted_at IS NULL"
    )
    row = await cur.fetchone()
    return row[0] if row else 0


async def update_user_status(
    db: aiosqlite.Connection,
    user_id: str,
    *,
    is_disabled: bool | None = None,
    role: str | None = None,
) -> int:
    """更新禁用状态和/或角色（仅作用于未软删除用户）。返回受影响行数。"""
    sets: list[str] = []
    params: list = []
    if is_disabled is not None:
        sets.append("is_disabled = ?")
        params.append(1 if is_disabled else 0)
    if role is not None:
        sets.append("role = ?")
        params.append(role)
    if not sets:
        return 0
    sets.append("updated_at = ?")
    params.append(_now_iso())
    params.append(user_id)
    cur = await db.execute(
        f"UPDATE users SET {', '.join(sets)} WHERE id = ? AND deleted_at IS NULL",
        params,
    )
    await db.commit()
    return cur.rowcount


async def soft_delete_user(db: aiosqlite.Connection, user_id: str) -> int:
    """软删除（标记 deleted_at）。已软删除则返回 0。"""
    cur = await db.execute(
        "UPDATE users SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
        (_now_iso(), _now_iso(), user_id),
    )
    await db.commit()
    return cur.rowcount


async def restore_user(db: aiosqlite.Connection, user_id: str) -> int:
    """恢复软删除用户（清 deleted_at）。"""
    cur = await db.execute(
        "UPDATE users SET deleted_at = NULL, updated_at = ? WHERE id = ? AND deleted_at IS NOT NULL",
        (_now_iso(), user_id),
    )
    await db.commit()
    return cur.rowcount


async def update_password(db: aiosqlite.Connection, user_id: str, password_hash: str) -> int:
    """更新密码哈希（改密/重置）。仅作用于未软删除用户。"""
    cur = await db.execute(
        "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
        (password_hash, _now_iso(), user_id),
    )
    await db.commit()
    return cur.rowcount


async def bump_token_version(db: aiosqlite.Connection, user_id: str) -> None:
    """token 版本号 +1，使该用户所有旧 JWT 立即失效（改密/重置密码时调用）。"""
    await db.execute(
        "UPDATE users SET token_version = token_version + 1, updated_at = ? "
        "WHERE id = ? AND deleted_at IS NULL",
        (_now_iso(), user_id),
    )
    await db.commit()


async def update_last_login(db: aiosqlite.Connection, user_id: str) -> None:
    """登录成功后更新 last_login_at。"""
    await db.execute(
        "UPDATE users SET last_login_at = ? WHERE id = ?",
        (_now_iso(), user_id),
    )
    await db.commit()
