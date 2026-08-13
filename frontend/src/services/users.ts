import { http, type ApiResponse } from './http'

export interface User {
  id: string
  username: string
  email: string
  role: string
  is_disabled: boolean
  created_at: string
  updated_at: string
  last_login_at: string | null
}

export async function listUsers(): Promise<User[]> {
  const resp = await http.get<ApiResponse<{ items: User[]; total: number }>>('/admin/users')
  return resp.data.data.items
}

export async function updateUser(
  id: string,
  body: { is_disabled?: boolean; role?: string },
): Promise<User> {
  const resp = await http.patch<ApiResponse<User>>(`/admin/users/${id}`, body)
  return resp.data.data
}

export async function deleteUser(id: string): Promise<void> {
  await http.delete(`/admin/users/${id}`)
}

export async function resetPassword(id: string): Promise<string> {
  const resp = await http.post<ApiResponse<{ temporary_password: string }>>(
    `/admin/users/${id}/reset-password`,
  )
  return resp.data.data.temporary_password
}
