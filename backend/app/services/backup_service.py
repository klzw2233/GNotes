"""备份服务：SQLite 一致性快照 → gzip → AES-256-GCM 整体加密 → 上传 Google Drive。

修文档备份未加密瑕疵（NFR-08）：备份文件为 .enc 加密包，且包内数据库本身笔记也是密文（双层保护）。
"""
from __future__ import annotations

import asyncio
import gzip
import logging
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.core.encryption import get_file_cipher
from app.services.gdrive_client import GDriveClient

logger = logging.getLogger(__name__)

# 备份任务并发锁：防止手动与定时并发执行
_backup_lock = asyncio.Lock()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S_UTC")


def _vacuum_into(source_db: str, dest_path: Path) -> None:
    """用 VACUUM INTO 生成一致性二进制快照（只读事务，不阻塞 WAL 写入）。"""
    dest = dest_path.resolve().as_posix().replace("'", "''")
    conn = sqlite3.connect(source_db)
    try:
        conn.execute(f"VACUUM INTO '{dest}'")
    finally:
        conn.close()


def _do_backup_sync() -> dict:
    """同步执行：快照 → gzip → 加密 → 上传 → 保留策略。返回结果元信息。"""
    settings = get_settings()
    file_cipher = get_file_cipher()

    ts = _timestamp()
    db_name = f"backup_{ts}.db"
    gz_name = f"{db_name}.gz"
    enc_name = f"{db_name}.gz.enc"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        db_path = tmpdir / db_name
        gz_path = tmpdir / gz_name
        enc_path = tmpdir / enc_name

        # 1. VACUUM INTO 一致性快照
        _vacuum_into(settings.database_path, db_path)
        logger.info("已生成数据库快照: %s (%d bytes)", db_name, db_path.stat().st_size)

        # 2. gzip 压缩
        with open(db_path, "rb") as fin, gzip.open(gz_path, "wb") as fout:
            fout.write(fin.read())

        # 3. AES-256-GCM 整体加密（修瑕疵2）
        with open(gz_path, "rb") as f:
            gz_data = f.read()
        enc_blob = file_cipher.encrypt_bytes(gz_data)
        enc_path.write_bytes(enc_blob)
        logger.info("已加密备份包: %s (%d bytes)", enc_name, len(enc_blob))

        # 4. 上传 Google Drive
        if not settings.google_drive_folder_id:
            raise RuntimeError("GOOGLE_DRIVE_FOLDER_ID 未配置，无法上传备份")

        client = GDriveClient(
            settings.google_drive_credentials_file,
            settings.google_drive_folder_id,
        )
        drive_file_id = client.upload_file(str(enc_path), enc_name)
        logger.info("已上传备份到 Google Drive: %s (file_id=%s)", enc_name, drive_file_id)

        # 5. 保留策略：删除超出数量的最旧备份
        _apply_retention(client, settings.backup_retention_count)

        return {
            "filename": enc_name,
            "size_bytes": len(enc_blob),
            "drive_file_id": drive_file_id,
        }


def _apply_retention(client: GDriveClient, retention_count: int) -> None:
    """删除超出保留数量的最旧备份文件。"""
    try:
        files = client.list_backup_files()
        if len(files) <= retention_count:
            return
        to_delete = files[: len(files) - retention_count]
        for f in to_delete:
            client.delete_file(f["id"])
            logger.info("已删除过期备份: %s", f["name"])
    except Exception:
        logger.exception("保留策略执行失败（不影响本次备份）")


async def run_backup() -> dict:
    """异步入口：阻塞操作放线程池，避免卡事件循环。"""
    async with _backup_lock:
        return await asyncio.to_thread(_do_backup_sync)
