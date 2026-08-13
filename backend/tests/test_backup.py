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
    """初始化 DB + 密钥 + 建一个真实用户 + 一条真实密文笔记（可被恢复验证解密）。"""
    from app.core.config import get_settings
    from app.core.encryption import init_ciphers, get_note_cipher
    from app.db.connection import get_db, init_db

    settings = get_settings()
    init_ciphers(settings.encryption_key_bytes, settings.backup_encryption_key_bytes)
    await init_db()
    nc = get_note_cipher()
    note_id, user_id = "n1", "u1"
    title_enc, title_nonce = nc.encrypt_field("测试标题", note_id, user_id)
    content_enc, content_nonce = nc.encrypt_field("测试正文", note_id, user_id)
    from app.db.connection import get_db
    async with get_db() as db:
        await db.execute(
            """INSERT INTO users (id, username, email, password_hash, role, created_at, updated_at)
               VALUES ('u1','testuser','t@e.com','hash','user','t','t')"""
        )
        await db.execute(
            """INSERT INTO notes (id, user_id, title_encrypted, title_nonce,
                                  content_encrypted, content_nonce, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (note_id, user_id, title_enc, title_nonce, content_enc, content_nonce, "t", "t"),
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
    """未配置 Drive 时 run_backup 抛错并写入 backup_runs，调用方捕获后进程应继续。"""
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "")
    from app.core import config as config_mod
    config_mod.get_settings.cache_clear()

    from app.services import backup_service
    with pytest.raises(RuntimeError):
        await backup_service.run_backup()

    status = await backup_service.get_backup_status()
    assert status["ok"] is False
    assert status["configured"] is False
    assert "Google Drive" in status["message"]
    assert status["consecutive_failures"] == 1


# ---------- P0 新增用例：持久化、恢复验证、重试、误删防护 ----------


@pytest.mark.asyncio
async def test_backup_run_persisted_and_verified(initialized_db: None) -> None:
    """备份成功后 backup_runs 应有一条 success 记录，且 verify_status=='ok'。"""
    mock_client = MagicMock()
    mock_client.upload_file.return_value = "fid"
    mock_client.list_backup_files.return_value = []

    with patch("app.services.backup_service.GDriveClient", return_value=mock_client):
        from app.services.backup_service import run_backup
        result = await run_backup()

    assert result["verify_status"] == "ok"

    from app.repositories import backup_run_repo
    from app.db.connection import get_db
    async with get_db() as db:
        latest = await backup_run_repo.get_latest(db)
    assert latest is not None
    assert latest["status"] == "success"
    assert latest["filename"] == result["filename"]
    assert latest["drive_file_id"] == "fid"
    assert latest["verify_status"] == "ok"


@pytest.mark.asyncio
async def test_backup_failure_recorded_with_message(initialized_db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """upload_file 抛错 → backup_runs 有 failed 记录 + error_message。"""
    from unittest.mock import MagicMock
    mock_client = MagicMock()
    mock_client.upload_file.side_effect = RuntimeError("网络断了")
    mock_client.list_backup_files.return_value = []

    with patch("app.services.backup_service.GDriveClient", return_value=mock_client):
        from app.services.backup_service import run_backup
        with pytest.raises(RuntimeError):
            await run_backup()

    from app.repositories import backup_run_repo
    from app.db.connection import get_db
    async with get_db() as db:
        latest = await backup_run_repo.get_latest(db)
        consec = await backup_run_repo.count_consecutive_failures(db)
    assert latest["status"] == "failed"
    assert latest["error_message"]  # 有错误信息
    assert latest["filename"] is None
    assert consec == 1


@pytest.mark.asyncio
async def test_retention_skips_non_gnotes_files(initialized_db: None) -> None:
    """保留策略：文件夹里混入非 backup_ 前缀/非 .db.gz.enc 后缀的文件，绝不能删。"""
    from app.core.config import get_settings
    get_settings().backup_retention_count = 3

    files = [
        # 合法 GNotes 备份（应删最旧的）
        {"id": "f1", "name": "backup_old.db.gz.enc", "createdTime": "1"},
        # 用户的其他文件——虽被 name contains 'backup_' 查询带回，但后缀不符，跳过
        {"id": "f2", "name": "backup_mynotes.txt", "createdTime": "2"},
        # 不带 backup_ 前缀（正常不会进列表，但若进来了也跳过）
        {"id": "f3", "name": "random_file.db.gz.enc", "createdTime": "3"},
        {"id": "f4", "name": "backup_new1.db.gz.enc", "createdTime": "4"},
    ]
    mock_client = MagicMock()
    mock_client.upload_file.return_value = "new_fid"
    mock_client.list_backup_files.return_value = files
    deleted: list[str] = []
    mock_client.delete_file.side_effect = lambda fid: deleted.append(fid)

    with patch("app.services.backup_service.GDriveClient", return_value=mock_client):
        from app.services.backup_service import run_backup
        await run_backup()

    # 只删了 f1（唯一既超量又满足双条件的旧文件）；f2/f3 被跳过，f4 是新备份本身范围外
    assert "f1" in deleted
    assert "f2" not in deleted
    assert "f3" not in deleted


@pytest.mark.asyncio
async def test_status_survives_cache_clear_simulating_restart(initialized_db: None) -> None:
    """写记录后清 settings/cipher 缓存重新查，状态仍在（模拟容器重启）。"""
    mock_client = MagicMock()
    mock_client.upload_file.return_value = "fid"
    mock_client.list_backup_files.return_value = []

    with patch("app.services.backup_service.GDriveClient", return_value=mock_client):
        from app.services.backup_service import run_backup
        await run_backup()

    # 清缓存模拟重启
    from app.core import config as config_mod
    from app.core import encryption as enc_mod
    config_mod.get_settings.cache_clear()
    enc_mod._note_cipher = None
    enc_mod._file_cipher = None

    from app.services.backup_service import get_backup_status
    status = await get_backup_status()
    assert status["ok"] is True
    assert status["drive_file_id"] == "fid"
    assert status["verify_status"] == "ok"
    assert status["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_verify_detects_tampered_backup() -> None:
    """恢复验证：篡改密文 → verify_status='failed'（不依赖 Drive）。"""
    from app.services.backup_service import verify_backup_integrity
    from app.core.encryption import get_file_cipher
    enc_blob = get_file_cipher().encrypt_bytes(b"\x1f\x8bfake-not-real-gzip")  # 能解密但解压/校验失败
    status, msg = verify_backup_integrity(None, enc_blob)
    assert status == "failed"
    assert msg


def test_gdrive_upload_retries_on_5xx_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """GDriveClient.upload_file：前两次 503、第三次成功 → 最终成功（tenacity 重试）。

    直接测真实 GDriveClient 的重试逻辑，mock service 层 create().execute() 抛 HttpError。
    patch time.sleep 避免退避等待拖慢测试。
    """
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)
    from unittest.mock import MagicMock
    from googleapiclient.errors import HttpError

    class FakeResp:
        def __init__(self, s):
            self.status = s
            self.reason = f"HTTP {s}"

    from app.services.gdrive_client import GDriveClient

    tmp = Path(__file__).parent / "_tmp_upload.bin"
    tmp.write_bytes(b"x")
    try:
        service = MagicMock()
        attempts = {"n": 0}

        def create_side(*a, **k):
            attempts["n"] += 1
            m = MagicMock()
            if attempts["n"] < 3:
                m.execute.side_effect = HttpError(FakeResp(503), b"transient")
            else:
                m.execute.return_value = {"id": "FILEID", "size": 0}
            return m

        service.files.return_value.create.side_effect = create_side
        get_chain = MagicMock()
        get_chain.execute.return_value = {"size": "1"}  # 与本地 1 字节一致
        service.files.return_value.get.return_value = get_chain

        client = GDriveClient.__new__(GDriveClient)
        client._credentials_file = "x"
        client._folder_id = "fid"
        client._service = service

        fid = client.upload_file(str(tmp), "backup_test.db.gz.enc")
        assert fid == "FILEID"
        assert attempts["n"] == 3
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass

