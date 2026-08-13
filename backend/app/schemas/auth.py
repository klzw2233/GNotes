"""认证相关 Pydantic 模型。"""
from __future__ import annotations

from typing import Literal

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
    """用户信息响应（不含密码哈希）。"""
    id: str
    username: str
    email: str
    role: str
    is_disabled: bool = False
    created_at: str
    updated_at: str
    last_login_at: str | None = None


class UserListResponse(BaseModel):
    items: list[UserOut]
    total: int


class UserUpdate(BaseModel):
    """管理员更新用户状态/角色入参。至少传一个字段。"""
    is_disabled: bool | None = None
    role: Literal["user", "admin"] | None = None


class ResetPasswordResponse(BaseModel):
    """重置密码响应：临时密码仅本次返回明文。"""
    temporary_password: str


class ChangePasswordRequest(BaseModel):
    """用户修改自己密码入参。"""
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=72)
