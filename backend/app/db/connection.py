"""SQLite 连接管理：aiosqlite + WAL + 外键开启。"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from app.core.config import get_settings

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


async def init_db() -> None:
    """启动时执行：确保数据目录存在、应用 schema、开启 WAL 与外键。"""
    settings = get_settings()
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    db = await aiosqlite.connect(settings.database_path)
    try:
        await db.execute("PRAGMA journal_mode=WAL;")  # 提升并发读
        await db.execute("PRAGMA foreign_keys=ON;")
        await db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
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
