"""Google Drive 上传客户端（服务账号）。独立封装便于测试时 mock。

P0-2/P0-3 改进：
- 上传加 tenacity 退避重试（2s/5s/15s，最多 3 次），只重试 5xx 与网络错误/大小不符，
  4xx（认证/权限/文件不存在）直接失败并分类。
- 上传后用 files().get(fields='size') 做大小软校验：上传成功但大小不符视为失败重试。
- 保留策略只处理 GNotes 自己生成的 backup_*.db.gz.enc 文件，防误删用户其他文件。
- 新增 download_file 供恢复验证/历史备份下载。
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from tenacity import (
    RetryError,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# 可重试的 HTTP 状态码：服务端瞬时错误
_RETRYABLE_STATUS = {500, 502, 503, 504}


class _TransientError(Exception):
    """可重试的瞬时错误（5xx / 网络 / 上传大小不符）。"""


class GDriveClient:
    """Google Drive 服务账号客户端封装。"""

    def __init__(self, credentials_file: str, folder_id: str) -> None:
        self._credentials_file = credentials_file
        self._folder_id = folder_id
        self._service = None

    def _get_service(self):
        if self._service is None:
            creds = service_account.Credentials.from_service_account_file(
                self._credentials_file, scopes=SCOPES
            )
            self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._service

    @staticmethod
    def _classify(exc: BaseException) -> BaseException:
        """把底层异常归为可重试(_TransientError) 或直接失败(原样抛)。

        - 5xx → _TransientError（重试）
        - 网络/超时 → _TransientError（重试）
        - 上传后大小不符 → _TransientError（重试）
        - 4xx（403/404 等）→ 原样抛（不重试，由上层分类提示）
        """
        if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
            return _TransientError(str(exc))
        if isinstance(exc, HttpError):
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status in _RETRYABLE_STATUS:
                return _TransientError(f"Drive HTTP {status}")
            return exc  # 4xx：直接失败
        return exc

    def upload_file(self, local_path: str, name: str) -> str:
        """上传文件到目标文件夹，返回 Drive file_id。

        带 tenacity 退避重试（≈2s/5s/15s，最多 3 次）。上传后做大小软校验。
        重试耗尽抛 RuntimeError，由 backup_service 转人类可读错误。
        """
        local_size = Path(local_path).stat().st_size

        # 退避：multiplier=2, exp=1,2 → 约 2s, 4s（在 2/5/15 的量级内），max=15
        retryer = Retrying(
            retry=retry_if_exception_type(_TransientError),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=2, max=15),
            reraise=True,
        )

        def _do() -> str:
            try:
                service = self._get_service()
                media = MediaFileUpload(local_path, resumable=True)
                body = {"name": name, "parents": [self._folder_id]}
                created = (
                    service.files()
                    .create(body=body, media_body=media, fields="id, size")
                    .execute()
                )
                file_id = created["id"]
                # 软校验：Drive 记录的大小应与本地一致（上传不完整会被重试）
                got = (
                    service.files()
                    .get(fileId=file_id, fields="size")
                    .execute()
                )
                drive_size = int(got.get("size", 0))
                if drive_size != local_size:
                    logger.warning(
                        "上传后大小不符：本地 %d / Drive %d，将重试", local_size, drive_size
                    )
                    raise _TransientError(f"size mismatch {drive_size} != {local_size}")
                return file_id
            except BaseException as exc:
                raise self._classify(exc) from exc

        try:
            return retryer(_do)
        except _TransientError as exc:
            raise RuntimeError(f"Drive 上传重试 3 次仍失败: {exc}") from exc

    def list_backup_files(self) -> list[dict]:
        """列出目标文件夹下的备份文件（按创建时间升序）。

        P0-2 修正：查询加 `name contains 'backup_'`，只列 GNotes 自己生成的文件，
        避免保留策略误删用户放进同一文件夹的其他文件。
        """
        service = self._get_service()
        results = (
            service.files()
            .list(
                q=f"'{self._folder_id}' in parents and trashed = false and name contains 'backup_'",
                fields="files(id, name, createdTime)",
                orderBy="createdTime",
                pageSize=200,
            )
            .execute()
        )
        return results.get("files", [])

    def delete_file(self, file_id: str) -> None:
        service = self._get_service()
        service.files().delete(fileId=file_id).execute()

    def download_file(self, file_id: str) -> bytes:
        """下载指定 file_id 的文件内容（供恢复验证/历史备份下载）。"""
        service = self._get_service()
        request = service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request, chunksize=1024 * 1024)
        done = False
        while not done:
            _status, done = downloader.next_chunk()
        return buf.getvalue()
