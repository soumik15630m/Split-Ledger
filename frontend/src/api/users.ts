import { api } from './client'
import type { AuthResponse, User, ApiSuccess } from '@/types'
import type { RegisterPayload, LoginPayload } from '@/types'

export const usersApi = {
  register: async (payload: RegisterPayload): Promise<AuthResponse> => {
    const res = await api.post<ApiSuccess<AuthResponse>>('/auth/register', payload)
    return res.data.data
  },

  login: async (payload: LoginPayload): Promise<AuthResponse> => {
    const res = await api.post<ApiSuccess<AuthResponse>>('/auth/login', payload)
    return res.data.data
  },

  refresh: async (refreshToken: string): Promise<{ access_token: string; refresh_token: string }> => {
    const res = await api.post<ApiSuccess<{ access_token: string; refresh_token: string }>>(
      '/auth/refresh',
      { refresh_token: refreshToken },
    )
    return res.data.data
  },

  logout: async (refreshToken: string): Promise<void> => {
    await api.post('/auth/logout', { refresh_token: refreshToken })
  },

  me: async (): Promise<User> => {
    const res = await api.get<ApiSuccess<User>>('/auth/me')
    return res.data.data
  },
}
