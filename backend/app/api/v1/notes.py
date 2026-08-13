"""笔记路由：/notes CRUD + 列表。所有操作经 deps 校验身份，service 层做 user_id 隔离。"""
from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user, get_db_dep
from app.schemas.common import ok
from app.schemas.notes import NoteCreate, NoteListItem, NoteListResponse, NoteOut, NoteUpdate
from app.services import note_service

router = APIRouter(prefix="/notes", tags=["notes"])


@router.get("")
async def list_notes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db_dep),
) -> dict:
    items, total = await note_service.list_notes(db, user["id"], page, page_size)
    return ok(
        NoteListResponse(
            items=[NoteListItem(**it) for it in items],
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump()
    )


@router.get("/{note_id}")
async def get_note(
    note_id: str,
    user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db_dep),
) -> dict:
    note = await note_service.get_note_decrypted(db, note_id, user["id"])
    if not note:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "笔记不存在")
    return ok(NoteOut(**note).model_dump())


@router.post("")
async def create_note(
    body: NoteCreate,
    user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db_dep),
) -> dict:
    note_id = await note_service.create_note(
        db, user_id=user["id"], title=body.title, content=body.content
    )
    return ok({"id": note_id}, message="已创建")


@router.put("/{note_id}")
async def update_note(
    note_id: str,
    body: NoteUpdate,
    user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db_dep),
) -> dict:
    updated = await note_service.update_note(
        db, note_id=note_id, user_id=user["id"], title=body.title, content=body.content
    )
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "笔记不存在")
    return ok(message="已更新")


@router.delete("/{note_id}")
async def delete_note(
    note_id: str,
    user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db_dep),
) -> dict:
    deleted = await note_service.delete_note(db, note_id, user["id"])
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "笔记不存在")
    return ok(message="已删除")
