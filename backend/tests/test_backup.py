"""备份模块测试：验证 快照→gzip→加密→上传 链路，用 mock 替换真实 Google Drive。

核心验证（修瑕疵2）：上传给 Drive 的是 .enc 加密包，无法直接 gunzip，
必须用 BACKUP_ENCRYPTION_KEY 解密后才能还原数据库。
"""
from __future__ import annotations

import base64
import gzip
import secrets
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
async def initialized_db() -> None:
    """初始化 DB + 密钥 + 建一个真实用户 + 一条密文笔记。"""
    from app.core.config import get_settings
    from app.core.encryption import init_ciphers
    from app.db.connection import get_db, init_db

    settings = get_settings()
    init_ciphers(settings.encryption_key_bytes, settings.backup_encryption_key_bytes)
    await init_db()
    async with get_db() as db:
        await db.execute(
            """INSERT INTO users (id, username, email, password_hash, role, created_at, updated_at)
               VALUES ('u1','testuser','t@e.com','hash','user','t','t')"""
        )
        await db.execute(
            """INSERT INTO notes (id, user_id, title_encrypted, title_nonce,
                                  content_encrypted, content_nonce, created_at, updated_at)
               VALUES ('n1','u1','enc','nonce','enc','nonce','t','t')"""
        )
        await db.commit()


@pytest.mark.asyncio
async def test_backup_produces_encrypted_file_not_gunzippable(
    initialized_db: None,
) -> None:
    """上传给 Drive 的文件必须：以 .enc 结尾、且无法直接 gunzip（证明已加密）。"""
    uploaded: dict = {}

    def fake_upload(local_path: str, name: str) -> str:
        uploaded["name"] = name
        uploaded["size"] = Path(local_path).stat().st_size
        uploaded["bytes"] = Path(local_path).read_bytes()  # 临时目录会被清理，先读出来
        return "fake_drive_file_id"

    mock_client = MagicMock()
    mock_client.upload_file.side_effect = fake_upload
    mock_client.list_backup_files.return_value = []

    with patch(
        "app.services.backup_service.GDriveClient", return_value=mock_client
    ):
        from app.services.backup_service import run_backup
        result = await run_backup()

    # 文件名规范：backup_<ts>.db.gz.enc
    assert result["filename"].endswith(".db.gz.enc")
    assert "backup_" in result["filename"]
    assert result["drive_file_id"] == "fake_drive_file_id"
    assert result["size_bytes"] > 0

    # 上传的文件无法直接 gunzip（是加密的）
    with pytest.raises(Exception):
        gzip.decompress(uploaded["bytes"])


@pytest.mark.asyncio
async def test_backup_roundtrip_decrypt_restore(initialized_db: None) -> None:
    """整条链路：备份 → 用 BACKUP_ENCRYPTION_KEY 解密 → gunzip → 得到可用 SQLite 快照。"""
    mock_client = MagicMock()
    mock_client.upload_file.return_value = "fid"
    mock_client.list_backup_files.return_value = []

    with patch(
        "app.services.backup_service.GDriveClient", return_value=mock_client
    ):
        from app.services.backup_service import run_backup
        result = await run_backup()

    # 模拟从 Drive 下载回加密包（这里直接用上传时的本地文件——测试临时目录已清理，
    # 所以我们在 upload mock 里把它拷出来）
    # 改进：让 mock 保存内容
    uploaded_bytes = b""

    def fake_upload2(local_path: str, name: str) -> str:
        nonlocal uploaded_bytes
        uploaded_bytes = Path(local_path).read_bytes()
        return "fid2"

    mock_client2 = MagicMock()
    mock_client2.upload_file.side_effect = fake_upload2
    mock_client2.list_backup_files.return_value = []

    with patch(
        "app.services.backup_service.GDriveClient", return_value=mock_client2
    ):
        from app.services.backup_service import run_backup
        await run_backup()

    # 解密 → gunzip → 得到 SQLite 快照
    from app.core.encryption import get_file_cipher
    decrypted_gz = get_file_cipher().decrypt_bytes(uploaded_bytes)
    db_bytes = gzip.decompress(decrypted_gz)

    # 写到临时文件，用 sqlite3 打开验证结构完整
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        f.write(db_bytes)
        snapshot_path = f.name

    conn = sqlite3.connect(snapshot_path)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()
    table_names = {t[0] for t in tables}
    assert "notes" in table_names
    assert "users" in table_names


@pytest.mark.asyncio
async def test_retention_deletes_oldest(initialized_db: None) -> None:
    """保留策略：超出数量时删除最旧的。"""
    # settings 默认 BACKUP_RETENTION_COUNT=30，测试设为 3
    from app.core.config import get_settings
    get_settings().backup_retention_count = 3

    # Drive 上已有 5 个文件，保留 3 个 → 应删 2 个最旧
    files = [
        {"id": "f1", "name": "backup_old1.db.gz.enc", "createdTime": "1"},
        {"id": "f2", "name": "backup_old2.db.gz.enc", "createdTime": "2"},
        {"id": "f3", "name": "backup_old3.db.gz.enc", "createdTime": "3"},
        {"id": "f4", "name": "backup_new1.db.gz.enc", "createdTime": "4"},
        {"id": "f5", "name": "backup_new2.db.gz.enc", "createdTime": "5"},
    ]
    mock_client = MagicMock()
    mock_client.upload_file.return_value = "new_fid"
    mock_client.list_backup_files.return_value = files
    deleted: list[str] = []
    mock_client.delete_file.side_effect = lambda fid: deleted.append(fid)

    with patch(
        "app.services.backup_service.GDriveClient", return_value=mock_client
    ):
        from app.services.backup_service import run_backup
        await run_backup()

    assert "f1" in deleted
    assert "f2" in deleted
    assert "f5" not in deleted


@pytest.mark.asyncio
async def test_run_backup_without_drive_records_failure(initialized_db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """未配置 Drive 时 run_backup 抛错并写入状态，调用方捕获后进程应继续。"""
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "")
    from app.core import config as config_mod
    config_mod.get_settings.cache_clear()

    from app.services import backup_service
    backup_service._last_status["ok"] = None

    with pytest.raises(RuntimeError):
        await backup_service.run_backup()

    status = backup_service.get_backup_status()
    assert status["ok"] is False
    assert status["configured"] is False
    assert "Google Drive" in status["message"]
