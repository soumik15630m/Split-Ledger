// ─────────────────────────────────────────────────────────────────────────────
// SplitLedger — API Client
// Axios instance with:
//   • Base URL from env
//   • Authorization header injection
//   • Auto-refresh on 401 (single in-flight refresh, queued retries)
//   • Unwraps { data, warnings } envelope
// ─────────────────────────────────────────────────────────────────────────────

import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import type { ApiError } from '@/types'

// ── Storage keys ──────────────────────────────────────────────────────────────

export const STORAGE_KEYS = {
  ACCESS:  'sl_access_token',
  REFRESH: 'sl_refresh_token',
} as const

export function getAccessToken()  { return localStorage.getItem(STORAGE_KEYS.ACCESS) }
export function getRefreshToken() { return localStorage.getItem(STORAGE_KEYS.REFRESH) }

export function storeTokens(access: string, refresh: string) {
  localStorage.setItem(STORAGE_KEYS.ACCESS,  access)
  localStorage.setItem(STORAGE_KEYS.REFRESH, refresh)
}

export function clearTokens() {
  localStorage.removeItem(STORAGE_KEYS.ACCESS)
  localStorage.removeItem(STORAGE_KEYS.REFRESH)
}

// ── Axios instance ─────────────────────────────────────────────────────────────

export const api = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
  timeout: 15_000,
})

// ── Request interceptor — inject access token ─────────────────────────────────

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ── Response interceptor — auto-refresh on 401 ───────────────────────────────

let _refreshing: Promise<string> | null = null

interface QueueEntry {
  resolve: (token: string) => void
  reject:  (err: unknown) => void
}
const _queue: QueueEntry[] = []

function _processQueue(token: string | null, err: unknown) {
  _queue.forEach(entry => {
    token ? entry.resolve(token) : entry.reject(err)
  })
  _queue.length = 0
}

api.interceptors.response.use(
  // Unwrap the success envelope — callers receive data directly
  response => {
    // The backend wraps everything in { data, warnings }
    // We pass through the full response so callers can access warnings if needed
    return response
  },
  async (error: AxiosError<ApiError>) => {
    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    // ── Token expired → try refresh ───────────────────────────────────────────
    if (
      error.response?.status === 401 &&
      error.response.data?.error?.code === 'TOKEN_EXPIRED' &&
      !original._retry
    ) {
      original._retry = true

      if (_refreshing) {
        // Queue this request until the in-flight refresh completes
        return new Promise((resolve, reject) => {
          _queue.push({
            resolve: (token) => {
              original.headers.Authorization = `Bearer ${token}`
              resolve(api(original))
            },
            reject,
          })
        })
      }

      const refreshToken = getRefreshToken()
      if (!refreshToken) {
        clearTokens()
        window.dispatchEvent(new Event('sl:logout'))
        return Promise.reject(error)
      }

      _refreshing = axios
        .post<{ data: { access_token: string; refresh_token: string } }>(
          '/api/v1/auth/refresh',
          { refresh_token: refreshToken },
        )
        .then(res => {
          const { access_token, refresh_token } = res.data.data
          storeTokens(access_token, refresh_token)
          _processQueue(access_token, null)
          return access_token
        })
        .catch(err => {
          _processQueue(null, err)
          clearTokens()
          window.dispatchEvent(new Event('sl:logout'))
          throw err
        })
        .finally(() => { _refreshing = null })

      const newToken = await _refreshing
      original.headers.Authorization = `Bearer ${newToken}`
      return api(original)
    }

    return Promise.reject(error)
  },
)

// ── Typed error extraction ────────────────────────────────────────────────────

export class ApiException extends Error {
  code:        string
  field?:      string
  httpStatus:  number

  constructor(code: string, message: string, httpStatus: number, field?: string) {
    super(message)
    this.name       = 'ApiException'
    this.code       = code
    this.field      = field
    this.httpStatus = httpStatus
  }
}

export function extractApiError(err: unknown): ApiException {
  if (err instanceof ApiException) return err
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as ApiError | undefined
    if (data?.error) {
      return new ApiException(
        data.error.code,
        data.error.message,
        err.response?.status ?? 500,
        data.error.field,
      )
    }
    return new ApiException('NETWORK_ERROR', err.message, 0)
  }
  return new ApiException('UNKNOWN_ERROR', 'An unexpected error occurred', 0)
}
