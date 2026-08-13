"""加密模块单测：往返、InvalidTag、AAD 绑定、nonce 随机性。"""
from __future__ import annotations

import base64
import secrets

import pytest
from cryptography.exceptions import InvalidTag

from app.core.encryption import FileCipher, NoteCipher


# ---------- fixtures ----------

@pytest.fixture
def key() -> bytes:
    return secrets.token_bytes(32)


@pytest.fixture
def note_cipher(key: bytes) -> NoteCipher:
    return NoteCipher(key)


@pytest.fixture
def file_cipher(key: bytes) -> FileCipher:
    return FileCipher(key)


NOTE_ID = "11111111-1111-1111-1111-111111111111"
USER_ID = "22222222-2222-2222-2222-222222222222"


# ---------- NoteCipher ----------

def test_note_encrypt_decrypt_roundtrip(note_cipher: NoteCipher) -> None:
    ciphertext, nonce = note_cipher.encrypt_field("hello 测试", NOTE_ID, USER_ID)
    plaintext = note_cipher.decrypt_field(ciphertext, nonce, NOTE_ID, USER_ID)
    assert plaintext == "hello 测试"


def test_note_ciphertext_not_equal_plaintext(note_cipher: NoteCipher) -> None:
    ciphertext, _ = note_cipher.encrypt_field("secret", NOTE_ID, USER_ID)
    assert "secret" not in ciphertext
    # 密文是 Base64，与原文无关
    assert ciphertext != base64.b64encode(b"secret").decode()


def test_note_tamper_raises_invalid_tag(note_cipher: NoteCipher) -> None:
    ciphertext, nonce = note_cipher.encrypt_field("data", NOTE_ID, USER_ID)
    # 翻转密文最后一个字节
    tampered = bytearray(base64.b64decode(ciphertext))
    tampered[-1] ^= 0xFF
    bad_ciphertext = base64.b64encode(bytes(tampered)).decode()
    with pytest.raises(InvalidTag):
        note_cipher.decrypt_field(bad_ciphertext, nonce, NOTE_ID, USER_ID)


def test_note_aad_mismatch_raises_invalid_tag(note_cipher: NoteCipher) -> None:
    """把 A 的密文解到 B 的行：AAD 不匹配必须拒绝（防剪贴攻击）。"""
    ciphertext, nonce = note_cipher.encrypt_field("A's note", NOTE_ID, USER_ID)
    other_user = "33333333-3333-3333-3333-333333333333"
    with pytest.raises(InvalidTag):
        note_cipher.decrypt_field(ciphertext, nonce, NOTE_ID, other_user)


def test_note_nonce_uniqueness(note_cipher: NoteCipher) -> None:
    """同一明文连续加密两次，nonce 必须不同（绝不复用 nonce）。"""
    _, n1 = note_cipher.encrypt_field("same", NOTE_ID, USER_ID)
    _, n2 = note_cipher.encrypt_field("same", NOTE_ID, USER_ID)
    assert n1 != n2


def test_note_title_and_content_independent_nonces(note_cipher: NoteCipher) -> None:
    """标题与正文各用独立 nonce。"""
    _, title_nonce = note_cipher.encrypt_field("标题", NOTE_ID, USER_ID)
    _, content_nonce = note_cipher.encrypt_field("正文", NOTE_ID, USER_ID)
    assert title_nonce != content_nonce


# ---------- FileCipher ----------

def test_file_encrypt_decrypt_roundtrip(file_cipher: FileCipher) -> None:
    data = b"sqlite database snapshot" * 1000
    blob = file_cipher.encrypt_bytes(data)
    assert file_cipher.decrypt_bytes(blob) == data


def test_file_blob_starts_with_nonce(file_cipher: FileCipher) -> None:
    blob = file_cipher.encrypt_bytes(b"abc")
    assert len(blob) == 12 + 3 + 16  # nonce + 明文 + tag


def test_file_tamper_raises_invalid_tag(file_cipher: FileCipher) -> None:
    blob = bytearray(file_cipher.encrypt_bytes(b"data"))
    blob[20] ^= 0xFF  # 篡改密文部分
    with pytest.raises(InvalidTag):
        file_cipher.decrypt_bytes(bytes(blob))


def test_file_short_blob_raises(file_cipher: FileCipher) -> None:
    with pytest.raises(ValueError):
        file_cipher.decrypt_bytes(b"short")


def test_invalid_key_length() -> None:
    with pytest.raises(ValueError):
        NoteCipher(b"too-short")
    with pytest.raises(ValueError):
        FileCipher(b"too-short")
