import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { authApi, type AuthUser } from '@/api/auth'
import { TOKEN_STORAGE_KEY, USER_STORAGE_KEY } from '@/api/index'

const readStoredUser = (): AuthUser | null => {
  try {
    const raw = localStorage.getItem(USER_STORAGE_KEY)
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem(TOKEN_STORAGE_KEY) || '')
  const user = ref<AuthUser | null>(readStoredUser())

  const isLoggedIn = computed(() => !!token.value)
  const displayName = computed(() => user.value?.display_name || user.value?.username || '')
  const mustChangePassword = computed(() => !!user.value?.must_change_password)

  const persist = () => {
    if (token.value) {
      localStorage.setItem(TOKEN_STORAGE_KEY, token.value)
    } else {
      localStorage.removeItem(TOKEN_STORAGE_KEY)
    }
    if (user.value) {
      localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user.value))
    } else {
      localStorage.removeItem(USER_STORAGE_KEY)
    }
  }

  const setSession = (newToken: string, newUser: AuthUser) => {
    token.value = newToken
    user.value = newUser
    persist()
  }

  const setUser = (newUser: AuthUser) => {
    user.value = newUser
    persist()
  }

  const clear = () => {
    token.value = ''
    user.value = null
    persist()
  }

  const login = async (username: string, password: string) => {
    const { data } = await authApi.login(username, password)
    setSession(data.access_token, data.user)
    return data.user
  }

  const changePassword = async (currentPassword: string, newPassword: string) => {
    const { data } = await authApi.changePassword(currentPassword, newPassword)
    setUser(data)
    return data
  }

  const logout = async () => {
    try {
      await authApi.logout()
    } catch {
      // Stateless JWT: clearing the client session is enough.
    }
    clear()
  }

  // Refresh the profile (also validates a stored token on first load).
  const refresh = async () => {
    if (!token.value) return null
    try {
      const { data } = await authApi.me()
      setUser(data)
      return data
    } catch {
      clear()
      return null
    }
  }

  return {
    token,
    user,
    isLoggedIn,
    displayName,
    mustChangePassword,
    login,
    logout,
    changePassword,
    refresh,
    clear
  }
})
