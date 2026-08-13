import axios from 'axios'

const TOKEN_KEY = 'gnotes_token'

export const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export const http = axios.create({ baseURL, timeout: 15000 })

// 请求拦截：注入 JWT
http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 统一响应类型
export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
}

// 响应拦截：统一解包 {code,message,data}；401 清 token 跳登录
http.interceptors.response.use(
  (response) => {
    const body = response.data as ApiResponse
    if (body && typeof body.code === 'number' && body.code !== 0) {
      // 业务错误（如 401 密码错误）：抛错给页面
      const err = new Error(body.message || '请求失败') as Error & { code?: number }
      err.code = body.code
      return Promise.reject(err)
    }
    return response
  },
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      // 跳登录（避免在拦截器里 import router 造成循环依赖，直接改 location）
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    const body = error.response?.data
    const message = (body && (body.message || body.detail)) || error.message || '网络错误'
    return Promise.reject(new Error(message))
  },
)

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
