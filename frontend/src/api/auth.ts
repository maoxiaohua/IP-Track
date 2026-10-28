import apiClient from './index'

export interface AuthUser {
  id: number
  username: string
  display_name?: string | null
  role: string
  must_change_password: boolean
}

export interface LoginResult {
  access_token: string
  token_type: string
  expires_in: number
  user: AuthUser
}

export const authApi = {
  // Login errors are shown by the form itself, so skip the global toast.
  login(username: string, password: string) {
    return apiClient.post<LoginResult>(
      '/api/v1/auth/login',
      { username, password },
      { skipDefaultErrorHandler: true } as any
    )
  },
  me() {
    return apiClient.get<AuthUser>('/api/v1/auth/me', { skipDefaultErrorHandler: true } as any)
  },
  changePassword(currentPassword: string, newPassword: string) {
    return apiClient.post<AuthUser>(
      '/api/v1/auth/change-password',
      { current_password: currentPassword, new_password: newPassword },
      { skipDefaultErrorHandler: true } as any
    )
  },
  logout() {
    return apiClient.post('/api/v1/auth/logout', {}, { skipDefaultErrorHandler: true } as any)
  }
}
