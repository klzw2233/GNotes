"""笔记业务编排：加密入库 / 解密出库。

核心：先生成不可变 note_id（UUID4），用它作 AAD 加密标题与正文，再入库。
读取时用同一 AAD 解密。更新时 note_id 不变、AAD 不变、重新生成 nonce 重加密。
"""
from __future__ import annotations

import uuid

import aiosqlite

from app.core.encryption import InvalidTag, get_note_cipher
from app.repositories import note_repo


async def create_note(
    db: aiosqlite.Connection, *, user_id: str, title: str, content: str
) -> str:
    """生成 note_id → AAD 加密标题/正文（各独立 nonce）→ 入库。返回 note_id。"""
    note_id = str(uuid.uuid4())
    cipher = get_note_cipher()
    title_enc, title_nonce = cipher.encrypt_field(title, note_id, user_id)
    content_enc, content_nonce = cipher.encrypt_field(content, note_id, user_id)
    await note_repo.create_note(
        db,
        note_id=note_id,
        user_id=user_id,
        title_encrypted=title_enc,
        title_nonce=title_nonce,
        content_encrypted=content_enc,
        content_nonce=content_nonce,
    )
    return note_id


async def get_note_decrypted(
    db: aiosqlite.Connection, note_id: str, user_id: str
) -> dict | None:
    """查单篇并解密标题+正文。不存在或不属于该用户返回 None。"""
    row = await note_repo.get_note(db, note_id, user_id)
    if not row:
        return None
    cipher = get_note_cipher()
    try:
        title = cipher.decrypt_field(
            row["title_encrypted"], row["title_nonce"], note_id, user_id
        )
        content = cipher.decrypt_field(
            row["content_encrypted"], row["content_nonce"], note_id, user_id
        )
    except InvalidTag:
        # AAD 不匹配或密文被篡改：拒绝返回，调用方应转 403/500
        return None
    return {
        "id": row["id"],
        "title": title,
        "content": content,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def list_notes(
    db: aiosqlite.Connection, user_id: str, page: int, page_size: int
) -> tuple[list[dict], int]:
    """列表：仅解密标题，不取正文密文进内存。"""
    rows, total = await note_repo.list_notes(db, user_id, page, page_size)
    cipher = get_note_cipher()
    items = []
    for row in rows:
        try:
            title = cipher.decrypt_field(
                row["title_encrypted"], row["title_nonce"], row["id"], user_id
            )
        except InvalidTag:
            title = "[解密失败]"
        items.append({
            "id": row["id"],
            "title": title,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })
    return items, total


async def update_note(
    db: aiosqlite.Connection,
    *,
    note_id: str,
    user_id: str,
    title: str,
    content: str,
) -> bool:
    """更新：note_id 不变（AAD 不变），重新生成 nonce 重加密。返回是否成功。"""
    if not await note_repo.get_note_for_update_check(db, note_id, user_id):
        return False
    cipher = get_note_cipher()
    title_enc, title_nonce = cipher.encrypt_field(title, note_id, user_id)
    content_enc, content_nonce = cipher.encrypt_field(content, note_id, user_id)
    affected = await note_repo.update_note(
        db,
        note_id=note_id,
        user_id=user_id,
        title_encrypted=title_enc,
        title_nonce=title_nonce,
        content_encrypted=content_enc,
        content_nonce=content_nonce,
    )
    return affected > 0


async def delete_note(db: aiosqlite.Connection, note_id: str, user_id: str) -> bool:
    return await note_repo.delete_note(db, note_id, user_id) > 0
