import { http, type ApiResponse } from './http'

export interface BackupRun {
  id: string
  status: string // 'success' | 'failed'
  filename: string | null
  size_bytes: number | null
  drive_file_id: string | null
  error_message: string | null
  verify_status: string | null // 'ok' | 'failed' | 'skipped'
  verify_message: string | null
  started_at: string
  finished_at: string
}

export interface BackupStatus {
  configured: boolean
  ok: boolean | null
  message: string
  filename: string | null
  size_bytes: number | null
  drive_file_id: string | null
  finished_at: string | null
  started_at: string | null
  verify_status: string | null
  verify_message: string | null
  consecutive_failures: number
  next_run_at: string | null
}

export async function getBackupStatus(): Promise<BackupStatus> {
  const resp = await http.get<ApiResponse<BackupStatus>>('/admin/backup')
  return resp.data.data
}

export async function triggerBackup(): Promise<void> {
  await http.post('/admin/backup')
}

export interface BackupRunsPage {
  items: BackupRun[]
  total: number
  page: number
  page_size: number
}

export async function getBackupHistory(page = 1, pageSize = 20): Promise<BackupRunsPage> {
  const resp = await http.get<ApiResponse<BackupRunsPage>>(
    '/admin/backup/runs',
    { params: { page, page_size: pageSize } },
  )
  return resp.data.data
}
