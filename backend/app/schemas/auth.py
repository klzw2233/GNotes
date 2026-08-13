"""认证相关 Pydantic 模型。"""
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_in: int  # 秒
    role: str


class UserCreate(BaseModel):
    """管理员创建用户入参。"""
    username: str = Field(min_length=1, max_length=64)
    email: EmailStr
    password: str = Field(min_length=6, max_length=72)  # bcrypt 只吃前 72 字节


class UserOut(BaseModel):
    id: str
    username: str
    email: str
    role: str
