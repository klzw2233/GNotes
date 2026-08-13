import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as authService from '../services/auth'
import { getToken, clearToken } from '../services/http'

const USERNAME_KEY = 'gnotes_username'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(getToken())
  const username = ref<string | null>(localStorage.getItem(USERNAME_KEY))

  const isAuthenticated = computed(() => !!token.value)

  async function login(usernameInput: string, password: string): Promise<void> {
    const result = await authService.login(usernameInput, password)
    token.value = result.token
    username.value = usernameInput
    localStorage.setItem(USERNAME_KEY, usernameInput)
  }

  async function logout(): Promise<void> {
    await authService.logout()
    token.value = null
    username.value = null
    clearToken()
    localStorage.removeItem(USERNAME_KEY)
  }

  return { token, username, isAuthenticated, login, logout }
})
