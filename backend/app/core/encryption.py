"""AES-256-GCM 加密封装：NoteCipher（笔记字段）+ FileCipher（备份整文件）。

安全要点：
- 每次加密生成随机 12 字节 nonce，绝不在同一 Key 下复用（修文档 Nonce 复用瑕疵）。
- NoteCipher 用 note_id:user_id 作 AAD，把密文绑定到特定行与属主，防剪贴攻击。
- 密文与 nonce 以 Base64 字符串存入 SQLite TEXT 列。
"""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

NONCE_BYTES = 12  # GCM 推荐 96 位 nonce


def _b64encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64decode(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))


class NoteCipher:
    """笔记标题/正文字段加解密。每个字段独立 nonce + AAD 绑定。"""

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError(f"密钥必须为 32 字节，实际 {len(key)} 字节")
        self._aesgcm = AESGCM(key)

    @staticmethod
    def _aad(note_id: str, user_id: str) -> bytes:
        return f"{note_id}:{user_id}".encode("utf-8")

    def encrypt_field(self, plaintext: str, note_id: str, user_id: str) -> tuple[str, str]:
        """加密单个字段，返回 (ciphertext_b64, nonce_b64)。nonce 随机生成。"""
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = self._aesgcm.encrypt(
            nonce, plaintext.encode("utf-8"), self._aad(note_id, user_id)
        )
        return _b64encode(ciphertext), _b64encode(nonce)

    def decrypt_field(self, ciphertext_b64: str, nonce_b64: str, note_id: str, user_id: str) -> str:
        """解密单个字段。AAD 不匹配或密文被篡改抛 InvalidTag。"""
        plaintext = self._aesgcm.decrypt(
            _b64decode(nonce_b64), _b64decode(ciphertext_b64), self._aad(note_id, user_id)
        )
        return plaintext.decode("utf-8")


class FileCipher:
    """备份整文件加解密。格式：nonce(12) ‖ ciphertext+tag。"""

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError(f"密钥必须为 32 字节，实际 {len(key)} 字节")
        self._aesgcm = AESGCM(key)

    def encrypt_bytes(self, data: bytes) -> bytes:
        """加密，返回 nonce(12) ‖ ciphertext+tag。"""
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = self._aesgcm.encrypt(nonce, data, None)
        return nonce + ciphertext

    def decrypt_bytes(self, blob: bytes) -> bytes:
        """解密。前 12 字节为 nonce，其余为密文。"""
        if len(blob) < NONCE_BYTES:
            raise ValueError("密文过短，无法提取 nonce")
        nonce, ciphertext = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
        return self._aesgcm.decrypt(nonce, ciphertext, None)


# 单例（在应用启动时由 main.py 注入密钥；这里提供懒加载以便测试直接用）
_note_cipher: NoteCipher | None = None
_file_cipher: FileCipher | None = None


def get_note_cipher() -> NoteCipher:
    global _note_cipher
    if _note_cipher is None:
        from app.core.config import get_settings
        _note_cipher = NoteCipher(get_settings().encryption_key_bytes)
    return _note_cipher


def get_file_cipher() -> FileCipher:
    global _file_cipher
    if _file_cipher is None:
        from app.core.config import get_settings
        _file_cipher = FileCipher(get_settings().backup_encryption_key_bytes)
    return _file_cipher


def init_ciphers(note_key: bytes, file_key: bytes | None = None) -> None:
    """启动时注入密钥（main.py lifespan 调用）。"""
    global _note_cipher, _file_cipher
    _note_cipher = NoteCipher(note_key)
    _file_cipher = FileCipher(file_key or note_key)


__all__ = [
    "InvalidTag",
    "NoteCipher",
    "FileCipher",
    "get_note_cipher",
    "get_file_cipher",
    "init_ciphers",
]
