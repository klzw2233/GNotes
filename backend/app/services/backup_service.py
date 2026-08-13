"""备份服务：SQLite 一致性快照 → gzip → AES-256-GCM 整体加密 → 上传 Google Drive。

P0 改进：
- 备份历史持久化到 backup_runs 表（替代进程内存 _last_status，重启不丢）。
- 备份成功后自动跑恢复完整性验证（integrity_check + 表存在 + 解密一条笔记）。
- _do_backup_sync 入口检查临时目录磁盘空间。
"""
from __future__ import annotations

import asyncio
import gzip
import logging
import shutil
import sqlite3
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from app.core.config import get_settings
from app.core.encryption import (
    InvalidTag,
    FileCipher,
    NoteCipher,
    get_file_cipher,
    get_note_cipher,
)
from app.repositories import backup_run_repo
from app.services.gdrive_client import GDriveClient

logger = logging.getLogger(__name__)

# 备份任务并发锁：防止手动与定时并发执行（重试期间持锁不释放，符合预期）
_backup_lock = asyncio.Lock()


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
    if "重试" in text or "retry" in lowered:
        return "Google Drive 上传多次失败，请检查网络或服务账号"
    return "备份失败，请查看服务器日志"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S_UTC")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vacuum_into(source_db: str, dest_path: Path) -> None:
    """用 VACUUM INTO 生成一致性二进制快照（只读事务，不阻塞 WAL 写入）。"""
    dest = dest_path.resolve().as_posix().replace("'", "''")
    conn = sqlite3.connect(source_db)
    try:
        conn.execute(f"VACUUM INTO '{dest}'")
    finally:
        conn.close()


def _check_disk_space(tmpdir: Path) -> None:
    """临时目录可用空间不足则提前失败（P0-5）。"""
    settings = get_settings()
    usage = shutil.disk_usage(str(tmpdir))
    free_mb = usage.free // (1024 * 1024)
    if free_mb < settings.backup_min_disk_mb:
        raise RuntimeError(
            f"临时目录可用空间不足：{free_mb}MB < {settings.backup_min_disk_mb}MB"
        )


def _do_backup_sync() -> dict:
    """同步执行：快照 → gzip → 加密 → 上传 → 保留策略。返回结果元信息（含 enc_path 供验证）。"""
    settings = get_settings()
    file_cipher = get_file_cipher()

    ts = _timestamp()
    db_name = f"backup_{ts}.db"
    gz_name = f"{db_name}.gz"
    enc_name = f"{db_name}.gz.enc"

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)

        # 0. 磁盘空间检查（P0-5）
        _check_disk_space(tmpdir)

        db_path = tmpdir / db_name
        gz_path = tmpdir / gz_name
        enc_path = tmpdir / enc_name

        # 1. VACUUM INTO 一致性快照
        _vacuum_into(settings.database_path, db_path)
        logger.info("已生成数据库快照: %s (%d bytes)", db_name, db_path.stat().st_size)

        # 2. gzip 压缩
        with open(db_path, "rb") as fin, gzip.open(gz_path, "wb") as fout:
            fout.write(fin.read())

        # 3. AES-256-GCM 整体加密
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

        # 6. 恢复完整性验证（P0-4）：用本地 enc_path，无需重新下载
        verify_status, verify_message = "skipped", None
        if settings.backup_verify_enabled:
            verify_status, verify_message = verify_backup_integrity(
                enc_path, enc_blob, file_cipher, get_note_cipher()
            )
            logger.info("恢复验证结果: %s — %s", verify_status, verify_message)

        return {
            "filename": enc_name,
            "size_bytes": len(enc_blob),
            "drive_file_id": drive_file_id,
            "verify_status": verify_status,
            "verify_message": verify_message,
        }


def verify_backup_integrity(
    enc_path: Path,
    enc_blob: bytes | None = None,
    file_cipher: FileCipher | None = None,
    note_cipher: NoteCipher | None = None,
) -> tuple[str, str]:
    """恢复完整性验证（P0-4）。

    1. 读 enc（优先用内存 enc_blob，省一次落盘）
    2. FileCipher 解密 → gzip 解压 → 写临时 db
    3. PRAGMA integrity_check 应为 ok
    4. users / notes 表存在
    5. 取一条 notes 行，用 NoteCipher 解密标题，不抛 InvalidTag 即通过

    返回 (verify_status, verify_message)：'ok' | 'failed'。
    """
    if file_cipher is None:
        file_cipher = get_file_cipher()
    if note_cipher is None:
        note_cipher = get_note_cipher()
    if enc_blob is None:
        enc_blob = Path(enc_path).read_bytes()

    try:
        gz_data = file_cipher.decrypt_bytes(enc_blob)
        db_bytes = gzip.decompress(gz_data)
    except Exception as exc:
        return "failed", f"解密/解压失败: {exc.__class__.__name__}"

    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            tf.write(db_bytes)
            temp_db = tf.name
        try:
            conn = sqlite3.connect(temp_db)
            try:
                cur = conn.execute("PRAGMA integrity_check")
                result = cur.fetchone()
                if not result or result[0] != "ok":
                    return "failed", f"integrity_check 非 ok: {result}"
                # 表存在性
                tables = {
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if "users" not in tables or "notes" not in tables:
                    return "failed", f"缺少必要表，实际: {sorted(tables)}"
                # 解密一条笔记
                row = conn.execute(
                    "SELECT id, user_id, title_encrypted, title_nonce FROM notes LIMIT 1"
                ).fetchone()
                if row:
                    note_id, user_id, title_enc, title_nonce = row
                    try:
                        note_cipher.decrypt_field(title_enc, title_nonce, note_id, user_id)
                    except InvalidTag:
                        return "failed", "笔记解密失败（AAD 不匹配或密文被篡改）"
                verify_msg = "已验证可恢复"
                if row:
                    verify_msg += "（含解密 1 条笔记）"
                else:
                    verify_msg += "（无笔记数据，跳过解密验证）"
                return "ok", verify_msg
            finally:
                conn.close()
        finally:
            try:
                Path(temp_db).unlink()
            except OSError:
                pass
    except Exception as exc:
        return "failed", f"验证过程异常: {exc.__class__.__name__}"


def _apply_retention(client: GDriveClient, retention_count: int) -> None:
    """删除超出保留数量的最旧备份文件。

    P0-2：双重防护。list_backup_files 已按 `name contains 'backup_'` 过滤，
    这里对每个待删文件再校验 startswith('backup_') and endswith('.db.gz.enc')，
    两者都满足才删；否则跳过并记 warning（绝不删看起来不像 GNotes 备份的文件）。
    """
    try:
        files = client.list_backup_files()
        if len(files) <= retention_count:
            return
        to_delete = files[: len(files) - retention_count]
        for f in to_delete:
            name = f.get("name", "")
            if name.startswith("backup_") and name.endswith(".db.gz.enc"):
                client.delete_file(f["id"])
                logger.info("已删除过期备份: %s", name)
            else:
                logger.warning("保留策略跳过非 GNotes 备份文件: %s (id=%s)", name, f.get("id"))
    except Exception:
        logger.exception("保留策略执行失败（不影响本次备份）")


async def get_backup_status() -> dict:
    """当前配置是否齐全 + 最近一次备份结果（查表，重启不丢）。

    无参签名：内部用独立短连接查 backup_runs。next_run_at 由 admin 路由层
    从 app.state.scheduler 注入（backup_service 不持有 app 引用）。
    """
    settings = get_settings()
    cred = Path(settings.google_drive_credentials_file)
    configured = bool(settings.google_drive_folder_id) and cred.is_file()

    async with _status_db() as db:
        latest = await backup_run_repo.get_latest(db)
        consecutive_failures = await backup_run_repo.count_consecutive_failures(db)

    if latest:
        return {
            "configured": configured,
            "ok": latest["status"] == "success",
            "message": latest.get("error_message") or (
                "备份已上传到 Google Drive" if latest["status"] == "success" else "备份失败"
            ),
            "filename": latest.get("filename"),
            "size_bytes": latest.get("size_bytes"),
            "drive_file_id": latest.get("drive_file_id"),
            "finished_at": latest.get("finished_at"),
            "started_at": latest.get("started_at"),
            "verify_status": latest.get("verify_status"),
            "verify_message": latest.get("verify_message"),
            "consecutive_failures": consecutive_failures,
        }
    return {
        "configured": configured,
        "ok": None,
        "message": "尚未执行过备份",
        "filename": None,
        "size_bytes": None,
        "drive_file_id": None,
        "finished_at": None,
        "started_at": None,
        "verify_status": None,
        "verify_message": None,
        "consecutive_failures": 0,
    }


async def run_backup() -> dict:
    """异步入口：阻塞操作放线程池。成功/失败都写 backup_runs 记录，失败时抛出。"""
    settings = get_settings()
    async with _backup_lock:
        started_at = _now_iso()
        try:
            result = await asyncio.to_thread(_do_backup_sync)
        except Exception as exc:
            message = _public_error_message(exc)
            logger.exception("备份失败: %s", message)
            # 失败也记一条，独立 try/except 防止写记录失败掩盖原异常
            try:
                async with _status_db() as db:
                    await backup_run_repo.create_run(
                        db,
                        status="failed",
                        error_message=message,
                        started_at=started_at,
                        finished_at=_now_iso(),
                    )
            except Exception:
                logger.exception("写 backup_runs 失败记录失败")
            raise
        # 成功：写记录（含验证结果）
        try:
            async with _status_db() as db:
                run_id = await backup_run_repo.create_run(
                    db,
                    status="success",
                    filename=result.get("filename"),
                    size_bytes=result.get("size_bytes"),
                    drive_file_id=result.get("drive_file_id"),
                    verify_status=result.get("verify_status"),
                    verify_message=result.get("verify_message"),
                    started_at=started_at,
                    finished_at=_now_iso(),
                )
            result["run_id"] = run_id
        except Exception:
            logger.exception("写 backup_runs 成功记录失败")
        return result


@asynccontextmanager
async def _status_db() -> AsyncIterator[aiosqlite.Connection]:
    """写 backup_runs 用的独立短连接（不依赖请求级 get_db，因 run_backup 不在请求上下文）。"""
    from app.db.connection import get_db
    async with get_db() as db:
        yield db
