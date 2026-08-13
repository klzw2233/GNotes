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

# 最近一次备份结果（进程内，供 UI 查询；容器重启后清空）
_last_status: dict = {
    "configured": False,
    "ok": None,
    "message": "尚未执行过备份",
    "filename": None,
    "size_bytes": None,
    "drive_file_id": None,
    "finished_at": None,
}


def _public_error_message(exc: BaseException) -> str:
    """给前端看的短错误，不回传内部路径或 SDK 堆栈。"""
    settings = get_settings()
    if not settings.google_drive_folder_id:
        return "未配置 Google Drive（GOOGLE_DRIVE_FOLDER_ID 为空），备份已跳过上传"
    cred = Path(settings.google_drive_credentials_file)
    if not cred.is_file():
        return "未找到 Google Drive 凭证文件，请将服务账号 JSON 放到 secrets/gdrive.json"
    text = str(exc)
    lowered = text.lower()
    if "folder" in lowered or "file not found" in lowered or "404" in lowered:
        return "无法访问 Google Drive 文件夹，请确认已分享给服务账号"
    if "credential" in lowered or "auth" in lowered or "403" in lowered:
        return "Google Drive 认证失败，请检查服务账号 JSON"
    return "备份失败，请查看服务器日志"


def get_backup_status() -> dict:
    """当前配置是否齐全 + 最近一次备份结果。"""
    settings = get_settings()
    cred = Path(settings.google_drive_credentials_file)
    configured = bool(settings.google_drive_folder_id) and cred.is_file()
    return {**_last_status, "configured": configured}


def _record_success(result: dict) -> None:
    _last_status.update(
        {
            "ok": True,
            "message": "备份已上传到 Google Drive",
            "filename": result.get("filename"),
            "size_bytes": result.get("size_bytes"),
            "drive_file_id": result.get("drive_file_id"),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def _record_failure(message: str) -> None:
    _last_status.update(
        {
            "ok": False,
            "message": message,
            "filename": None,
            "size_bytes": None,
            "drive_file_id": None,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    )


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

        # 4. 上传 Google Drive（缺 folder_id 时明确失败，不打挂进程）
        if not settings.google_drive_folder_id:
            raise RuntimeError("GOOGLE_DRIVE_FOLDER_ID 未配置")

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
    """异步入口：阻塞操作放线程池。失败记录状态后抛出，由调用方决定是否上浮。"""
    async with _backup_lock:
        try:
            result = await asyncio.to_thread(_do_backup_sync)
        except Exception as exc:
            message = _public_error_message(exc)
            logger.exception("备份失败: %s", message)
            _record_failure(message)
            raise
        _record_success(result)
        return result
