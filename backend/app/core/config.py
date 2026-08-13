"""应用配置：从环境变量读取并校验。密钥长度不对则 fail-fast。"""
from __future__ import annotations

import base64
import logging
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

MIN_JWT_SECRET_LEN = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- 安全密钥 ---
    jwt_secret: str
    encryption_key: str  # Base64(32 bytes)
    backup_encryption_key: str | None = None  # 缺省回退 encryption_key

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_must_be_long_enough(cls, v: str) -> str:
        if len(v) < MIN_JWT_SECRET_LEN:
            raise ValueError(
                f"JWT_SECRET 至少 {MIN_JWT_SECRET_LEN} 字符，实际 {len(v)}"
            )
        return v

    # --- 初始管理员 ---
    initial_admin_username: str = "admin"
    initial_admin_password: str
    initial_admin_email: str

    # --- 数据库 ---
    database_path: str = "/app/data/notes.db"

    # --- Google Drive ---
    google_drive_credentials_file: str = "/app/secrets/gdrive.json"
    google_drive_folder_id: str = ""
    backup_schedule: str = "0 2 * * *"
    backup_retention_count: int = 30
    # P0-3/P0-4/P0-5 备份可靠性参数
    backup_retry_attempts: int = 3
    backup_verify_enabled: bool = True  # 备份成功后自动跑恢复验证
    backup_verify_download_retries: int = 2  # 手动验证下载重试（历史备份）
    backup_min_disk_mb: int = 100  # 临时目录最低可用空间（MB）

    # --- 其他 ---
    log_level: str = "INFO"
    debug: bool = False  # True 时开放 /docs；生产保持 False
    login_max_attempts: int = 10
    login_window_seconds: int = 300

    @property
    def encryption_key_bytes(self) -> bytes:
        """解码主密钥为 32 字节 raw bytes，长度不符则抛错（fail-fast）。"""
        key = base64.b64decode(self.encryption_key, validate=True)
        if len(key) != 32:
            raise ValueError(
                f"ENCRYPTION_KEY 必须解码为 32 字节，实际 {len(key)} 字节"
            )
        return key

    @property
    def backup_encryption_key_bytes(self) -> bytes:
        """备份密钥；缺省回退到主密钥并打 warning。"""
        if self.backup_encryption_key:
            key = base64.b64decode(self.backup_encryption_key, validate=True)
            if len(key) != 32:
                raise ValueError(
                    f"BACKUP_ENCRYPTION_KEY 必须解码为 32 字节，实际 {len(key)} 字节"
                )
            return key
        logger.warning(
            "BACKUP_ENCRYPTION_KEY 未设置，回退到 ENCRYPTION_KEY（建议独立设置以纵深防御）"
        )
        return self.encryption_key_bytes


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def setup_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
