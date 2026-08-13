"""用户管理后台测试：列表/禁用/改角色/软删除/重置密码/自我保护/权限。

复用 test_admin.py 的 client fixture 模式（ASGITransport + bootstrap 初始管理员）。
"""
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


async def _create_user(client: AsyncClient, admin_token: str, username: str) -> str:
    """通过 admin API 建普通用户，返回 user_id。"""
    r = await client.post(
        "/api/v1/admin/users",
        json={"username": username, "email": f"{username}@e.com", "password": "pass-123456"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.json()["code"] == 0
    return r.json()["data"]["id"]


# ---------- 用户列表 ----------

@pytest.mark.asyncio
async def test_list_users_shows_created_user(client: AsyncClient) -> None:
    admin_token = await _login(client, "admin", "admin-pass-123")
    await _create_user(client, admin_token, "alice")
    r = await client.get(
        "/api/v1/admin/users", headers={"Authorization": f"Bearer {admin_token}"}
    )
    data = r.json()["data"]
    assert data["total"] == 2  # admin + alice
    usernames = [u["username"] for u in data["items"]]
    assert "admin" in usernames and "alice" in usernames
    # UserOut 含新字段
    alice = next(u for u in data["items"] if u["username"] == "alice")
    assert alice["is_disabled"] is False
    assert "last_login_at" in alice


# ---------- 禁用/启用 ----------

@pytest.mark.asyncio
async def test_disable_user_then_token_invalidated(client: AsyncClient) -> None:
    """禁用用户后，其旧 JWT 下次请求即 401（即时生效，不等过期）。"""
    admin_token = await _login(client, "admin", "admin-pass-123")
    await _create_user(client, admin_token, "alice")
    alice_token = await _login(client, "alice", "pass-123456")

    # alice 能访问
    r = await client.get("/api/v1/notes", headers={"Authorization": f"Bearer {alice_token}"})
    assert r.status_code == 200

    # admin 禁用 alice
    users = (await client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
             ).json()["data"]["items"]
    alice_id = next(u["id"] for u in users if u["username"] == "alice")
    r = await client.patch(
        f"/api/v1/admin/users/{alice_id}",
        json={"is_disabled": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.json()["code"] == 0
    assert r.json()["data"]["is_disabled"] is True

    # alice 旧 token 下次请求 → 401 账户已被禁用
    r = await client.get("/api/v1/notes", headers={"Authorization": f"Bearer {alice_token}"})
    assert r.status_code == 401
    assert "禁用" in r.json()["detail"]

    # 被禁用用户也不能登录
    r = await client.post("/api/v1/auth/login", json={"username": "alice", "password": "pass-123456"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_disable_then_enable_restores_access(client: AsyncClient) -> None:
    admin_token = await _login(client, "admin", "admin-pass-123")
    await _create_user(client, admin_token, "alice")
    users = (await client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
             ).json()["data"]["items"]
    alice_id = next(u["id"] for u in users if u["username"] == "alice")

    await client.patch(f"/api/v1/admin/users/{alice_id}", json={"is_disabled": True},
                       headers={"Authorization": f"Bearer {admin_token}"})
    r = await client.patch(f"/api/v1/admin/users/{alice_id}", json={"is_disabled": False},
                           headers={"Authorization": f"Bearer {admin_token}"})
    assert r.json()["data"]["is_disabled"] is False
    # 启用后能登录
    r = await client.post("/api/v1/auth/login", json={"username": "alice", "password": "pass-123456"})
    assert r.status_code == 200


# ---------- 改角色 ----------

@pytest.mark.asyncio
async def test_change_role(client: AsyncClient) -> None:
    admin_token = await _login(client, "admin", "admin-pass-123")
    uid = await _create_user(client, admin_token, "alice")
    r = await client.patch(
        f"/api/v1/admin/users/{uid}", json={"role": "admin"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.json()["data"]["role"] == "admin"


# ---------- 软删除 ----------

@pytest.mark.asyncio
async def test_soft_delete_user_cannot_login(client: AsyncClient) -> None:
    admin_token = await _login(client, "admin", "admin-pass-123")
    uid = await _create_user(client, admin_token, "alice")
    # 先建 token
    alice_token = await _login(client, "alice", "pass-123456")

    r = await client.delete(f"/api/v1/admin/users/{uid}",
                            headers={"Authorization": f"Bearer {admin_token}"})
    assert r.json()["code"] == 0

    # 软删除用户旧 token 即时 401
    r = await client.get("/api/v1/notes", headers={"Authorization": f"Bearer {alice_token}"})
    assert r.status_code == 401

    # 不能登录
    r = await client.post("/api/v1/auth/login", json={"username": "alice", "password": "pass-123456"})
    assert r.status_code == 401

    # 不出现在列表中
    users = (await client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
             ).json()["data"]["items"]
    assert not any(u["username"] == "alice" for u in users)


# ---------- 重置密码 ----------

@pytest.mark.asyncio
async def test_reset_password_temporary_works(client: AsyncClient) -> None:
    admin_token = await _login(client, "admin", "admin-pass-123")
    uid = await _create_user(client, admin_token, "alice")
    r = await client.post(
        f"/api/v1/admin/users/{uid}/reset-password",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    temp_pw = r.json()["data"]["temporary_password"]
    assert len(temp_pw) >= 12

    # 临时密码可登录（旧密码失效）
    r = await client.post("/api/v1/auth/login", json={"username": "alice", "password": "pass-123456"})
    assert r.status_code == 401
    r = await client.post("/api/v1/auth/login", json={"username": "alice", "password": temp_pw})
    assert r.status_code == 200


# ---------- 自我保护 ----------

@pytest.mark.asyncio
async def test_admin_cannot_disable_self(client: AsyncClient) -> None:
    admin_token = await _login(client, "admin", "admin-pass-123")
    admin_id = (
        await client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    ).json()["data"]["items"][0]["id"]
    r = await client.patch(
        f"/api/v1/admin/users/{admin_id}", json={"is_disabled": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 400
    assert "自己" in r.json()["detail"]


@pytest.mark.asyncio
async def test_admin_cannot_delete_self(client: AsyncClient) -> None:
    admin_token = await _login(client, "admin", "admin-pass-123")
    admin_id = (
        await client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    ).json()["data"]["items"][0]["id"]
    r = await client.delete(f"/api/v1/admin/users/{admin_id}",
                            headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_cannot_disable_last_admin(client: AsyncClient) -> None:
    """唯一管理员不能被禁用/降级。"""
    admin_token = await _login(client, "admin", "admin-pass-123")
    admin_id = (
        await client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    ).json()["data"]["items"][0]["id"]
    # 禁用自己已被自我保护拦截（400 自己），这里测降级
    r = await client.patch(
        f"/api/v1/admin/users/{admin_id}", json={"role": "user"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 400
    assert "最后" in r.json()["detail"]


# ---------- 改密 ----------

@pytest.mark.asyncio
async def test_change_password(client: AsyncClient) -> None:
    admin_token = await _login(client, "admin", "admin-pass-123")
    # 改密
    r = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "admin-pass-123", "new_password": "new-pass-123456"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.json()["code"] == 0
    # 旧密码登录失败
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin-pass-123"})
    assert r.status_code == 401
    # 新密码登录成功
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "new-pass-123456"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_change_password_wrong_old(client: AsyncClient) -> None:
    admin_token = await _login(client, "admin", "admin-pass-123")
    r = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "wrong", "new_password": "new-pass-123456"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 401
    assert "旧密码" in r.json()["detail"]


# ---------- 权限 ----------

@pytest.mark.asyncio
async def test_non_admin_cannot_access_user_management(client: AsyncClient) -> None:
    admin_token = await _login(client, "admin", "admin-pass-123")
    await _create_user(client, admin_token, "alice")
    alice_token = await _login(client, "alice", "pass-123456")
    h = {"Authorization": f"Bearer {alice_token}"}
    assert (await client.get("/api/v1/admin/users", headers=h)).status_code == 403
    assert (await client.patch("/api/v1/admin/users/x", json={"is_disabled": True}, headers=h)).status_code == 403
    assert (await client.delete("/api/v1/admin/users/x", headers=h)).status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_blocked(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/admin/users")).status_code == 401
    assert (await client.post("/api/v1/auth/change-password",
             json={"old_password": "x", "new_password": "y"})).status_code == 401
