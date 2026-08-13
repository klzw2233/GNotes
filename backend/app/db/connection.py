"""SQLite 连接管理：aiosqlite + WAL + 外键开启。"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from app.core.config import get_settings

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# users 表的增量列迁移：ALTER TABLE ADD COLUMN 不支持 IF NOT EXISTS，
# 用 PRAGMA table_info 检查列是否存在，缺列才加。幂等，重复执行安全。
_USER_COLUMN_MIGRATIONS = [
    ("is_disabled", "ALTER TABLE users ADD COLUMN is_disabled INTEGER NOT NULL DEFAULT 0"),
    ("last_login_at", "ALTER TABLE users ADD COLUMN last_login_at TEXT"),
    ("deleted_at", "ALTER TABLE users ADD COLUMN deleted_at TEXT"),
    # P1-8：token 版本号，改密/重置密码时 +1，使旧 JWT 立即失效
    ("token_version", "ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"),
]


async def _migrate(db: aiosqlite.Connection) -> None:
    """增量列迁移：为 users 表补充 P1-6/7 新增列（幂等）。"""
    cur = await db.execute("PRAGMA table_info(users)")
    existing = {row[1] for row in await cur.fetchall()}
    for col, ddl in _USER_COLUMN_MIGRATIONS:
        if col not in existing:
            await db.execute(ddl)
            logger.info("已迁移 users 表新增列: %s", col)
    await db.commit()


async def init_db() -> None:
    """启动时执行：确保数据目录存在、应用 schema、增量迁移、开启 WAL 与外键。"""
    settings = get_settings()
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    db = await aiosqlite.connect(settings.database_path)
    try:
        await db.execute("PRAGMA journal_mode=WAL;")  # 提升并发读
        await db.execute("PRAGMA foreign_keys=ON;")
        await db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        await _migrate(db)
        await db.commit()
    finally:
        await db.close()


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    """FastAPI 依赖：每请求一个连接，开启外键。"""
    settings = get_settings()
    db = await aiosqlite.connect(settings.database_path)
    db.row_factory = aiosqlite.Row
    try:
        await db.execute("PRAGMA foreign_keys=ON;")
        yield db
    finally:
        await db.close()
