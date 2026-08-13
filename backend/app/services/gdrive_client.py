"""Google Drive 上传客户端（服务账号）。独立封装便于测试时 mock。"""
from __future__ import annotations

import logging
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


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

    def upload_file(self, local_path: str, name: str) -> str:
        """上传文件到目标文件夹，返回 Drive file_id。"""
        service = self._get_service()
        media = MediaFileUpload(local_path, resumable=True)
        body = {"name": name, "parents": [self._folder_id]}
        file = (
            service.files()
            .create(body=body, media_body=media, fields="id")
            .execute()
        )
        return file["id"]

    def list_backup_files(self) -> list[dict]:
        """列出目标文件夹下的备份文件（按创建时间升序）。"""
        service = self._get_service()
        results = (
            service.files()
            .list(
                q=f"'{self._folder_id}' in parents and trashed = false",
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
