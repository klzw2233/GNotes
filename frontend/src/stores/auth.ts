import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as authService from '../services/auth'
import { getToken, clearToken } from '../services/http'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(getToken())
  const username = ref<string | null>(null)

  const isAuthenticated = computed(() => !!token.value)

  async function login(usernameInput: string, password: string): Promise<void> {
    const result = await authService.login(usernameInput, password)
    token.value = result.token
    username.value = usernameInput
  }

  async function logout(): Promise<void> {
    await authService.logout()
    token.value = null
    username.value = null
    clearToken()
  }

  return { token, username, isAuthenticated, login, logout }
})
