import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as authService from '../services/auth'
import { getToken, clearToken } from '../services/http'

const USERNAME_KEY = 'gnotes_username'
const ROLE_KEY = 'gnotes_role'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(getToken())
  const username = ref<string | null>(localStorage.getItem(USERNAME_KEY))
  const role = ref<string | null>(localStorage.getItem(ROLE_KEY))

  const isAuthenticated = computed(() => !!token.value)
  const isAdmin = computed(() => role.value === 'admin')

  async function login(usernameInput: string, password: string): Promise<void> {
    const result = await authService.login(usernameInput, password)
    token.value = result.token
    username.value = usernameInput
    role.value = result.role
    localStorage.setItem(USERNAME_KEY, usernameInput)
    localStorage.setItem(ROLE_KEY, result.role)
  }

  async function logout(): Promise<void> {
    await authService.logout()
    token.value = null
    username.value = null
    role.value = null
    clearToken()
    localStorage.removeItem(USERNAME_KEY)
    localStorage.removeItem(ROLE_KEY)
  }

  return { token, username, role, isAuthenticated, isAdmin, login, logout }
})
