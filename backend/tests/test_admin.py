"""管理员接口测试：建用户、权限校验、重复检测。"""
from __future__ import annotations

from collections.abc import Iterator

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
    return (
        await client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
    ).json()["data"]["token"]


@pytest.mark.asyncio
async def test_admin_creates_user_then_user_can_login(client: AsyncClient) -> None:
    admin_token = await _login(client, "admin", "admin-pass-123")
    headers = {"Authorization": f"Bearer {admin_token}"}

    r = await client.post(
        "/api/v1/admin/users",
        json={
            "username": "newuser",
            "email": "new@example.com",
            "password": "newpass-123",
        },
        headers=headers,
    )
    assert r.json()["code"] == 0
    assert r.json()["data"]["username"] == "newuser"
    assert r.json()["data"]["role"] == "user"

    # 新用户能登录
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "newuser", "password": "newpass-123"},
    )
    assert r.json()["code"] == 0
    assert r.json()["data"]["token"]


@pytest.mark.asyncio
async def test_non_admin_cannot_create_user(client: AsyncClient) -> None:
    admin_token = await _login(client, "admin", "admin-pass-123")
    await client.post(
        "/api/v1/admin/users",
        json={"username": "u1", "email": "u1@e.com", "password": "pass-123"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    user_token = await _login(client, "u1", "pass-123")
    r = await client.post(
        "/api/v1/admin/users",
        json={"username": "u2", "email": "u2@e.com", "password": "pass-123"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_duplicate_username_rejected(client: AsyncClient) -> None:
    admin_token = await _login(client, "admin", "admin-pass-123")
    r = await client.post(
        "/api/v1/admin/users",
        json={"username": "admin", "email": "other@e.com", "password": "pass-123"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_unauthenticated_admin_blocked(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/admin/users",
        json={"username": "x", "email": "x@e.com", "password": "pass-123"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_backup_status_and_manual_failure_does_not_500_stack(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未配置 Drive 时：查询状态可用；手动备份返回 500 但不冒内部细节。"""
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "")
    from app.core import config as config_mod
    config_mod.get_settings.cache_clear()

    admin_token = await _login(client, "admin", "admin-pass-123")
    headers = {"Authorization": f"Bearer {admin_token}"}

    status = await client.get("/api/v1/admin/backup", headers=headers)
    assert status.status_code == 200
    data = status.json()["data"]
    assert data["configured"] is False

    r = await client.post("/api/v1/admin/backup", headers=headers)
    assert r.status_code == 500
    assert r.json()["detail"] == "备份失败"

    after = (await client.get("/api/v1/admin/backup", headers=headers)).json()["data"]
    assert after["ok"] is False
    assert "Google Drive" in after["message"]
