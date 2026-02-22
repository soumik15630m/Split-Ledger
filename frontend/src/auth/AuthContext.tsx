import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { usersApi } from '@/api/users'
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  storeTokens,
} from '@/api/client'
import type { User, LoginPayload, RegisterPayload } from '@/types'

// ─────────────────────────────────────────────────────────────────────────────

interface AuthState {
  user:          User | null
  isLoading:     boolean
  isAuthenticated: boolean
}

interface AuthActions {
  login:    (payload: LoginPayload)    => Promise<void>
  register: (payload: RegisterPayload) => Promise<void>
  logout:   () => Promise<void>
}

type AuthContextValue = AuthState & AuthActions

const AuthContext = createContext<AuthContextValue | null>(null)

// ─────────────────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser]         = useState<User | null>(null)
  const [isLoading, setLoading] = useState(true)
  const loggedOutRef            = useRef(false)

  // ── Boot: rehydrate user from stored token ────────────────────────────────
  useEffect(() => {
    const boot = async () => {
      const token = getAccessToken()
      if (!token) {
        setLoading(false)
        return
      }
      try {
        const me = await usersApi.me()
        setUser(me)
      } catch {
        // Token invalid or expired — clear and treat as logged out
        clearTokens()
      } finally {
        setLoading(false)
      }
    }
    boot()
  }, [])

  // ── Listen for forced logout (emitted by Axios interceptor on failed refresh)
  useEffect(() => {
    const handler = () => {
      if (!loggedOutRef.current) {
        loggedOutRef.current = true
        setUser(null)
        clearTokens()
      }
    }
    window.addEventListener('sl:logout', handler)
    return () => window.removeEventListener('sl:logout', handler)
  }, [])

  // ── Auth actions ──────────────────────────────────────────────────────────

  const login = async (payload: LoginPayload) => {
    const res = await usersApi.login(payload)
    storeTokens(res.access_token, res.refresh_token)
    setUser(res.user)
    loggedOutRef.current = false
  }

  const register = async (payload: RegisterPayload) => {
    const res = await usersApi.register(payload)
    storeTokens(res.access_token, res.refresh_token)
    setUser(res.user)
    loggedOutRef.current = false
  }

  const logout = async () => {
    const refreshToken = getRefreshToken()
    try {
      if (refreshToken) await usersApi.logout(refreshToken)
    } catch {
      // Best-effort — always clear local state
    } finally {
      clearTokens()
      setUser(null)
      loggedOutRef.current = true
    }
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        login,
        register,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

// ─────────────────────────────────────────────────────────────────────────────

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
