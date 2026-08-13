"""认证集成测试：login、admin bootstrap、依赖鉴权。

用 httpx ASGITransport 直连 FastAPI app，不启动真实服务器。
测试用 .env 通过 monkeypatch 注入。
"""
from __future__ import annotations

import base64
import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


# ---------- 测试用配置 ----------

TEST_DB = Path(__file__).parent / "_test_notes.db"
TEST_ENV = {
    "JWT_SECRET": secrets.token_urlsafe(48),
    "ENCRYPTION_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
    "INITIAL_ADMIN_USERNAME": "admin",
    "INITIAL_ADMIN_PASSWORD": "admin-pass-123",
    "INITIAL_ADMIN_EMAIL": "admin@example.com",
    "DATABASE_PATH": str(TEST_DB),
    "GOOGLE_DRIVE_FOLDER_ID": "test_folder_id",
}


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """注入测试环境变量并清理缓存的 settings/cipher 单例。"""
    for k, v in TEST_ENV.items():
        monkeypatch.setenv(k, v)

    # 清除 lru_cache，使测试用新环境重新读取
    from app.core import config as config_mod
    config_mod.get_settings.cache_clear()

    # 清除加密切件单例
    from app.core import encryption as enc_mod
    enc_mod._note_cipher = None
    enc_mod._file_cipher = None

    yield

    config_mod.get_settings.cache_clear()
    enc_mod._note_cipher = None
    enc_mod._file_cipher = None
    if TEST_DB.exists():
        TEST_DB.unlink()
    # 清理 WAL/SHM 残留
    for suffix in ("-wal", "-shm"):
        f = TEST_DB.with_suffix(TEST_DB.suffix + suffix)
        if f.exists():
            f.unlink()


@pytest.fixture
async def client() -> AsyncClient:
    # ASGITransport 不触发 lifespan，手动初始化 DB + 密钥 + 管理员
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


# ---------- 测试 ----------

@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_admin_bootstrap_creates_admin(client: AsyncClient) -> None:
    """应用启动时（lifespan）应已创建初始管理员。"""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin-pass-123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["token"]
    assert body["data"]["token_type"] == "bearer"
    assert body["data"]["expires_in"] == 7 * 86400


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong"},
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == 401


@pytest.mark.asyncio
async def test_login_unknown_user(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "nobody", "password": "whatever"},
    )
    assert resp.json()["code"] == 401


@pytest.mark.asyncio
async def test_protected_route_requires_token(client: AsyncClient) -> None:
    """未带 token 访问受保护路由应 401。"""
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_with_token(client: AsyncClient) -> None:
    token = (
        await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin-pass-123"},
        )
    ).json()["data"]["token"]
    resp = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == 0
