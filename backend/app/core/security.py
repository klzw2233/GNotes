"""安全工具：bcrypt 密码哈希 + JWT 签发/验证。"""
from __future__ import annotations

import datetime as dt
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings

ALGORITHM = "HS256"
TOKEN_TTL_DAYS = 7
BCRYPT_ROUNDS = 12


# ---------- 密码哈希 ----------

def hash_password(password: str) -> str:
    """bcrypt 哈希（含 salt），返回 60 字符哈希字符串。"""
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    ).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码与哈希是否匹配。"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


# ---------- JWT ----------

def create_access_token(user_id: str, role: str, token_version: int = 0) -> str:
    """签发 JWT，payload 含 sub/role/iat/exp/ver。

    token_version 写入 ver，改密/重置密码时 +1；get_current_user 比对
    payload.ver 与 user.token_version，不等则令牌已失效。
    """
    settings = get_settings()
    now = dt.datetime.now(dt.timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "ver": token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(days=TOKEN_TTL_DAYS)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """验证并解码 JWT。过期或签名错误抛异常。"""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])


__all__ = [
    "ALGORITHM",
    "TOKEN_TTL_DAYS",
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_access_token",
]
