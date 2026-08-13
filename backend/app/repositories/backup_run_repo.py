"""backup_runs 表数据访问层：持久化备份历史（修 TODO P0-1）。

替代 backup_service 里的进程内存状态：容器重启后管理员页仍可查到最近成功/失败、
连续失败次数、最近若干次记录，以及恢复验证结果。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import aiosqlite


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_run(
    db: aiosqlite.Connection,
    *,
    status: str,
    filename: str | None = None,
    size_bytes: int | None = None,
    drive_file_id: str | None = None,
    error_message: str | None = None,
    verify_status: str | None = None,
    verify_message: str | None = None,
    started_at: str,
    finished_at: str | None = None,
) -> str:
    """插入一条 backup_runs 记录，返回 run_id（UUID4）。"""
    run_id = str(uuid.uuid4())
    if finished_at is None:
        finished_at = _now_iso()
    await db.execute(
        """INSERT INTO backup_runs
           (id, status, filename, size_bytes, drive_file_id, error_message,
            verify_status, verify_message, started_at, finished_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (run_id, status, filename, size_bytes, drive_file_id, error_message,
         verify_status, verify_message, started_at, finished_at),
    )
    await db.commit()
    return run_id


async def update_verify(
    db: aiosqlite.Connection, run_id: str, verify_status: str, verify_message: str
) -> None:
    """备份成功后回填恢复验证结果。"""
    await db.execute(
        "UPDATE backup_runs SET verify_status = ?, verify_message = ? WHERE id = ?",
        (verify_status, verify_message, run_id),
    )
    await db.commit()


async def list_recent(db: aiosqlite.Connection, limit: int = 20) -> list[dict]:
    """最近 N 条备份记录（按开始时间倒序）。"""
    cur = await db.execute(
        """SELECT id, status, filename, size_bytes, drive_file_id, error_message,
                  verify_status, verify_message, started_at, finished_at
           FROM backup_runs
           ORDER BY started_at DESC
           LIMIT ?""",
        (limit,),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_latest(db: aiosqlite.Connection, status: str | None = None) -> dict | None:
    """最近一条备份记录，可按 status 过滤（'success'/'failed'）。"""
    if status is None:
        cur = await db.execute(
            """SELECT id, status, filename, size_bytes, drive_file_id, error_message,
                      verify_status, verify_message, started_at, finished_at
               FROM backup_runs
               ORDER BY started_at DESC
               LIMIT 1"""
        )
    else:
        cur = await db.execute(
            """SELECT id, status, filename, size_bytes, drive_file_id, error_message,
                      verify_status, verify_message, started_at, finished_at
               FROM backup_runs
               WHERE status = ?
               ORDER BY started_at DESC
               LIMIT 1""",
            (status,),
        )
    row = await cur.fetchone()
    return dict(row) if row else None


async def count_consecutive_failures(db: aiosqlite.Connection) -> int:
    """从最新记录往前数连续 status='failed' 的条数（成功记录打断计数）。"""
    rows = await list_recent(db, limit=100)
    count = 0
    for r in rows:
        if r["status"] == "failed":
            count += 1
        else:
            break
    return count
