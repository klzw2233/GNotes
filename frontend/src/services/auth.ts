import { http, setToken, clearToken, type ApiResponse } from './http'

export interface LoginResult {
  token: string
  token_type: string
  expires_in: number
  role: string
}

export async function login(username: string, password: string): Promise<LoginResult> {
  const resp = await http.post<ApiResponse<LoginResult>>('/auth/login', {
    username,
    password,
  })
  const data = resp.data.data
  setToken(data.token)
  return data
}

export async function logout(): Promise<void> {
  try {
    await http.post('/auth/logout')
  } finally {
    // 软登出：无论后端是否成功都清本地 token
    clearToken()
  }
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<string> {
  const resp = await http.post<ApiResponse<{ token: string; expires_in: number }>>(
    '/auth/change-password',
    {
      old_password: oldPassword,
      new_password: newPassword,
    },
  )
  // 改密后旧 token 已失效（token_version +1），用接口返回的新 token 续登
  const newToken = resp.data.data.token
  setToken(newToken)
  return newToken
}
