"""FastAPI 应用入口 + lifespan。

lifespan 启动时做四件事：
1. init_ciphers —— 注入主密钥与备份密钥（fail-fast 校验长度）
2. init_db —— 应用 schema、开启 WAL/外键
3. bootstrap_admin —— users 表为空时创建初始管理员
4. 启动 APScheduler 定时备份
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from app.core.config import get_settings, setup_logging
from app.core.encryption import init_ciphers
from app.db.connection import get_db, init_db
from app.services.auth_service import bootstrap_admin
from app.services.backup_service import run_backup

logger = logging.getLogger(__name__)


async def _scheduled_backup() -> None:
    """定时备份包装：失败只记日志，不让异常冒出调度器。"""
    try:
        result = await run_backup()
        logger.info("定时备份完成: %s", result.get("filename"))
    except Exception:
        # 状态已在 run_backup 里记录；此处只保证调度器不被异常打死
        logger.error("定时备份未成功（容器继续运行）")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging()
    logger.info("启动 GNotes 后端…")

    # 1. 加密切件 fail-fast 校验（密钥长度不对直接退出）
    init_ciphers(settings.encryption_key_bytes, settings.backup_encryption_key_bytes)
    logger.info("加密切件已初始化")

    # 2. 数据库
    await init_db()
    logger.info("数据库已初始化: %s", settings.database_path)

    # 3. 初始管理员
    async with get_db() as db:
        await bootstrap_admin(db)

    # 4. APScheduler 定时备份
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _scheduled_backup,
        CronTrigger.from_crontab(settings.backup_schedule),
        id="daily_backup",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("定时备份已启用: %s", settings.backup_schedule)

    yield

    scheduler.shutdown(wait=True)
    logger.info("GNotes 后端关闭")


_settings = get_settings()
app = FastAPI(
    title="GNotes",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _settings.debug else None,
    redoc_url="/redoc" if _settings.debug else None,
    openapi_url="/openapi.json" if _settings.debug else None,
)


# 路由挂载（阶段2先挂 auth，阶段3+4+5 逐步追加）
from app.api.v1 import admin, auth, notes  # noqa: E402

app.include_router(auth.router, prefix="/api/v1")
app.include_router(notes.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
