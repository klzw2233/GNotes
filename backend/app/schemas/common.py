"""统一响应格式 {code, message, data}（文档 §5.1）。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: T | None = None


def ok(data: Any = None, message: str = "success") -> dict[str, Any]:
    return {"code": 0, "message": message, "data": data}


def fail(code: int, message: str) -> dict[str, Any]:
    return {"code": code, "message": message, "data": None}
