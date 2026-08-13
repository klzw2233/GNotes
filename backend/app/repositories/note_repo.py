"""notes 表数据访问层：所有查询强制带 user_id 过滤实现数据隔离（FR-04/05）。"""
from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_note(
    db: aiosqlite.Connection,
    *,
    note_id: str,
    user_id: str,
    title_encrypted: str,
    title_nonce: str,
    content_encrypted: str,
    content_nonce: str,
) -> None:
    now = _now_iso()
    await db.execute(
        """INSERT INTO notes
           (id, user_id, title_encrypted, title_nonce, content_encrypted, content_nonce, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (note_id, user_id, title_encrypted, title_nonce, content_encrypted, content_nonce, now, now),
    )
    await db.commit()


async def get_note(db: aiosqlite.Connection, note_id: str, user_id: str) -> dict | None:
    """按 id+user_id 查单篇（含正文密文）。user_id 隔离：只能查到自己的。"""
    cur = await db.execute(
        "SELECT * FROM notes WHERE id = ? AND user_id = ?",
        (note_id, user_id),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def get_note_for_update_check(
    db: aiosqlite.Connection, note_id: str, user_id: str
) -> bool:
    """仅检查所有权是否存在（更新/删除前校验）。"""
    cur = await db.execute(
        "SELECT 1 FROM notes WHERE id = ? AND user_id = ?",
        (note_id, user_id),
    )
    return await cur.fetchone() is not None


async def update_note(
    db: aiosqlite.Connection,
    *,
    note_id: str,
    user_id: str,
    title_encrypted: str,
    title_nonce: str,
    content_encrypted: str,
    content_nonce: str,
) -> int:
    """更新标题+正文（重新生成 nonce）。返回受影响行数（0 表示无权或不存在）。"""
    now = _now_iso()
    cur = await db.execute(
        """UPDATE notes
           SET title_encrypted = ?, title_nonce = ?,
               content_encrypted = ?, content_nonce = ?,
               updated_at = ?
           WHERE id = ? AND user_id = ?""",
        (title_encrypted, title_nonce, content_encrypted, content_nonce, now, note_id, user_id),
    )
    await db.commit()
    return cur.rowcount


async def delete_note(db: aiosqlite.Connection, note_id: str, user_id: str) -> int:
    cur = await db.execute(
        "DELETE FROM notes WHERE id = ? AND user_id = ?",
        (note_id, user_id),
    )
    await db.commit()
    return cur.rowcount


async def list_notes(
    db: aiosqlite.Connection, user_id: str, page: int, page_size: int
) -> tuple[list[dict], int]:
    """列表（仅取标题密文，不取正文），按 updated_at desc 分页。返回 (items, total)。"""
    offset = (page - 1) * page_size
    cur = await db.execute(
        """SELECT id, title_encrypted, title_nonce, created_at, updated_at
           FROM notes
           WHERE user_id = ?
           ORDER BY updated_at DESC
           LIMIT ? OFFSET ?""",
        (user_id, page_size, offset),
    )
    rows = await cur.fetchall()
    items = [dict(r) for r in rows]

    cur = await db.execute("SELECT COUNT(*) FROM notes WHERE user_id = ?", (user_id,))
    total = (await cur.fetchone())[0]
    return items, total
