import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { Toaster } from 'react-hot-toast'
import { AuthProvider, useAuth } from '@/auth/AuthContext'
import { AppShell } from '@/components/layout/AppShell'
import { FullPageSpinner } from '@/components/ui/Spinner'
import { LoginPage }     from '@/pages/LoginPage'
import { RegisterPage }  from '@/pages/RegisterPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { GroupPage }     from '@/pages/GroupPage'

// ── Query client ──────────────────────────────────────────────────────────────
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime:          30_000,     // 30 s before refetch
      retry:              1,
      refetchOnWindowFocus: false,
    },
  },
})

// ── Auth guards ───────────────────────────────────────────────────────────────

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()
  if (isLoading)          return <FullPageSpinner />
  if (!isAuthenticated)   return <Navigate to="/login" replace />
  return <>{children}</>
}

function RedirectIfAuthed({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()
  if (isLoading)        return <FullPageSpinner />
  if (isAuthenticated)  return <Navigate to="/dashboard" replace />
  return <>{children}</>
}

// ── Router ────────────────────────────────────────────────────────────────────

function AppRoutes() {
  return (
    <Routes>
      {/* Public */}
      <Route
        path="/login"
        element={<RedirectIfAuthed><LoginPage /></RedirectIfAuthed>}
      />
      <Route
        path="/register"
        element={<RedirectIfAuthed><RegisterPage /></RedirectIfAuthed>}
      />

      {/* Protected — wrapped in AppShell */}
      <Route
        path="/dashboard"
        element={
          <RequireAuth>
            <AppShell>
              <DashboardPage />
            </AppShell>
          </RequireAuth>
        }
      />
      <Route
        path="/groups/:id"
        element={
          <RequireAuth>
            <AppShell>
              <GroupPage />
            </AppShell>
          </RequireAuth>
        }
      />

      {/* Fallback */}
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}

// ── Root ──────────────────────────────────────────────────────────────────────

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <AppRoutes />
          <Toaster
            position="bottom-right"
            toastOptions={{
              style: {
                background: '#1e1e1e',
                color:      '#f0ede6',
                border:     '1px solid #282828',
                fontFamily: '"IBM Plex Sans", sans-serif',
                fontSize:   '0.875rem',
              },
              success: { iconTheme: { primary: '#4ade80', secondary: '#0c0c0c' } },
              error:   { iconTheme: { primary: '#f87171', secondary: '#0c0c0c' } },
            }}
          />
        </AuthProvider>
      </BrowserRouter>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  )
}
