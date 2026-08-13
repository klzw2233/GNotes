import { http, type ApiResponse } from './http'

export interface BackupStatus {
  configured: boolean
  ok: boolean | null
  message: string
  filename: string | null
  size_bytes: number | null
  drive_file_id: string | null
  finished_at: string | null
}

export async function getBackupStatus(): Promise<BackupStatus> {
  const resp = await http.get<ApiResponse<BackupStatus>>('/admin/backup')
  return resp.data.data
}

export async function triggerBackup(): Promise<void> {
  await http.post('/admin/backup')
}
