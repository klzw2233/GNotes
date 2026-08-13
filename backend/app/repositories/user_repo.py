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
    cur = await db.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def get_user_by_email(db: aiosqlite.Connection, email: str) -> dict | None:
    cur = await db.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def get_user_by_id(db: aiosqlite.Connection, user_id: str) -> dict | None:
    cur = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def count_users(db: aiosqlite.Connection) -> int:
    cur = await db.execute("SELECT COUNT(*) FROM users")
    row = await cur.fetchone()
    return row[0] if row else 0
