"""笔记 CRUD 集成测试：数据隔离、密文存储、列表排序。"""
from __future__ import annotations

import base64
import secrets
from collections.abc import Iterator
from pathlib import Path

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from tests.test_auth import TEST_DB, TEST_ENV


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for k, v in TEST_ENV.items():
        monkeypatch.setenv(k, v)
    from app.core import config as config_mod
    config_mod.get_settings.cache_clear()
    from app.core import encryption as enc_mod
    enc_mod._note_cipher = None
    enc_mod._file_cipher = None
    yield
    config_mod.get_settings.cache_clear()
    enc_mod._note_cipher = None
    enc_mod._file_cipher = None
    if TEST_DB.exists():
        TEST_DB.unlink()
    for suffix in ("-wal", "-shm"):
        f = TEST_DB.with_suffix(TEST_DB.suffix + suffix)
        if f.exists():
            f.unlink()


@pytest.fixture
async def client() -> AsyncClient:
    from app.core.config import get_settings
    from app.core.encryption import init_ciphers
    from app.db.connection import get_db, init_db
    from app.services.auth_service import bootstrap_admin

    settings = get_settings()
    init_ciphers(settings.encryption_key_bytes, settings.backup_encryption_key_bytes)
    await init_db()
    async with get_db() as db:
        await bootstrap_admin(db)

    from app.main import app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c  # type: ignore[misc]


async def _login(client: AsyncClient, username: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    return resp.json()["data"]["token"]


async def _create_user(client: AsyncClient, admin_token: str, username: str, email: str) -> None:
    """临时直接写库创建普通用户（管理员建用户接口在阶段4）。"""
    from app.core.security import hash_password
    from app.db.connection import get_db
    from app.repositories import user_repo
    async with get_db() as db:
        await user_repo.create_user(
            db, username=username, email=email, password_hash=hash_password("pass-123456"),
            role="user",
        )


# ---------- 测试 ----------

@pytest.mark.asyncio
async def test_create_and_get_note(client: AsyncClient) -> None:
    token = await _login(client, "admin", "admin-pass-123")
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/api/v1/notes",
        json={"title": "测试标题", "content": "hello world"},
        headers=headers,
    )
    assert resp.json()["code"] == 0
    note_id = resp.json()["data"]["id"]

    resp = await client.get(f"/api/v1/notes/{note_id}", headers=headers)
    assert resp.json()["data"]["title"] == "测试标题"
    assert resp.json()["data"]["content"] == "hello world"


@pytest.mark.asyncio
async def test_db_stores_ciphertext_not_plaintext(client: AsyncClient) -> None:
    """数据库里 title_encrypted/content_encrypted 不得含明文。"""
    token = await _login(client, "admin", "admin-pass-123")
    await client.post(
        "/api/v1/notes",
        json={"title": "SecretTitle", "content": "SecretContent"},
        headers={"Authorization": f"Bearer {token}"},
    )

    async with aiosqlite.connect(str(TEST_DB)) as db:
        cur = await db.execute("SELECT title_encrypted, content_encrypted, title_nonce, content_nonce FROM notes")
        row = await cur.fetchone()
    title_enc, content_enc, title_nonce, content_nonce = row
    assert "SecretTitle" not in title_enc
    assert "SecretContent" not in content_enc
    assert title_nonce != content_nonce  # 标题/正文独立 nonce


@pytest.mark.asyncio
async def test_list_notes_excludes_content(client: AsyncClient) -> None:
    """列表只返标题明文，不返正文（FR-09）。"""
    token = await _login(client, "admin", "admin-pass-123")
    headers = {"Authorization": f"Bearer {token}"}
    for i in range(3):
        await client.post(
            "/api/v1/notes",
            json={"title": f"笔记{i}", "content": f"正文{i}"},
            headers=headers,
        )
    resp = await client.get("/api/v1/notes", headers=headers)
    data = resp.json()["data"]
    assert data["total"] == 3
    for item in data["items"]:
        assert "content" not in item  # 列表不含正文
        assert item["title"].startswith("笔记")


@pytest.mark.asyncio
async def test_list_notes_ordered_by_updated_desc(client: AsyncClient) -> None:
    token = await _login(client, "admin", "admin-pass-123")
    headers = {"Authorization": f"Bearer {token}"}
    ids = []
    for i in range(3):
        r = await client.post(
            "/api/v1/notes",
            json={"title": f"t{i}", "content": "c"},
            headers=headers,
        )
        ids.append(r.json()["data"]["id"])
    # 更新中间那条，使其 updated_at 最新
    await client.put(
        f"/api/v1/notes/{ids[1]}",
        json={"title": "updated", "content": "c2"},
        headers=headers,
    )
    resp = await client.get("/api/v1/notes", headers=headers)
    items = resp.json()["data"]["items"]
    assert items[0]["id"] == ids[1]  # 最近更新的排第一
    assert items[0]["title"] == "updated"


@pytest.mark.asyncio
async def test_user_isolation_cannot_access_others_notes(client: AsyncClient) -> None:
    """用户 A 不能 GET/PUT/DELETE 用户 B 的笔记。"""
    admin_token = await _login(client, "admin", "admin-pass-123")
    # 直接建两个普通用户
    await _create_user(client, admin_token, "alice", "alice@example.com")
    await _create_user(client, admin_token, "bob", "bob@example.com")

    alice_token = await _login(client, "alice", "pass-123456")
    bob_token = await _login(client, "bob", "pass-123456")

    # alice 建一篇笔记
    resp = await client.post(
        "/api/v1/notes",
        json={"title": "alice's note", "content": "private"},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    note_id = resp.json()["data"]["id"]

    # bob 尝试访问 → 404（user_id 隔离，对 bob 而言不存在）
    r = await client.get(
        f"/api/v1/notes/{note_id}", headers={"Authorization": f"Bearer {bob_token}"}
    )
    assert r.status_code == 404
    # bob 尝试更新 → 404
    r = await client.put(
        f"/api/v1/notes/{note_id}",
        json={"title": "hacked", "content": "x"},
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert r.status_code == 404
    # bob 尝试删除 → 404
    r = await client.delete(
        f"/api/v1/notes/{note_id}", headers={"Authorization": f"Bearer {bob_token}"}
    )
    assert r.status_code == 404

    # alice 仍能正常访问
    r = await client.get(
        f"/api/v1/notes/{note_id}", headers={"Authorization": f"Bearer {alice_token}"}
    )
    assert r.json()["data"]["content"] == "private"


@pytest.mark.asyncio
async def test_unauthenticated_notes_blocked(client: AsyncClient) -> None:
    r = await client.get("/api/v1/notes")
    assert r.status_code == 401
    r = await client.post("/api/v1/notes", json={"title": "x", "content": "y"})
    assert r.status_code == 401
