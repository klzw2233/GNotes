"""笔记相关 Pydantic 模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=100_000)


class NoteUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=100_000)


class NoteOut(BaseModel):
    """详情响应：标题+正文明文。"""
    id: str
    title: str
    content: str
    created_at: str
    updated_at: str


class NoteListItem(BaseModel):
    """列表项：仅标题明文+元数据，不含正文。"""
    id: str
    title: str
    created_at: str
    updated_at: str


class NoteListResponse(BaseModel):
    items: list[NoteListItem]
    total: int
    page: int
    page_size: int
