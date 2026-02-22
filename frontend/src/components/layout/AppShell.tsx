import { Link, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import { Avatar } from '@/components/ui/Avatar'
import { Spinner } from '@/components/ui/Spinner'
import type { ReactNode } from 'react'

interface AppShellProps {
  children: ReactNode
}

export function AppShell({ children }: AppShellProps) {
  const { user, logout } = useAuth()
  const navigate         = useNavigate()

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  return (
    <div className="min-h-screen flex bg-bg">
      {/* ── Sidebar ──────────────────────────────────────────────────────── */}
      <aside className="w-60 shrink-0 border-r border-border flex flex-col bg-surface">
        {/* Logo */}
        <Link
          to="/dashboard"
          className="flex items-center gap-3 px-5 py-5 border-b border-border
                     hover:bg-surface2 transition-colors"
        >
          <div className="w-8 h-8 rounded-lg bg-ledger-green/15 border border-ledger-green/30
                          flex items-center justify-center">
            <span className="text-ledger-green font-mono font-bold text-sm">₹</span>
          </div>
          <span className="font-display text-lg text-text tracking-tight">SplitLedger</span>
        </Link>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5">
          <NavItem to="/dashboard" icon="⬡" label="Groups" />
        </nav>

        {/* User footer */}
        {user && (
          <div className="border-t border-border p-3">
            <div className="flex items-center gap-3 px-2 py-2 rounded-lg
                            hover:bg-surface2 transition-colors group">
              <Avatar name={user.username} size="sm" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-text truncate">{user.username}</p>
                <p className="text-xs text-text-3 truncate">{user.email}</p>
              </div>
              <button
                onClick={handleLogout}
                className="opacity-0 group-hover:opacity-100 transition-opacity
                           text-text-3 hover:text-ledger-red text-xs"
                title="Log out"
              >
                ⏻
              </button>
            </div>
          </div>
        )}
      </aside>

      {/* ── Main content ──────────────────────────────────────────────────── */}
      <main className="flex-1 overflow-y-auto">
        {children}
      </main>
    </div>
  )
}

// ── Nav item ──────────────────────────────────────────────────────────────────
function NavItem({ to, icon, label }: { to: string; icon: string; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors
         ${isActive
           ? 'bg-ledger-green/10 text-ledger-green font-medium border border-ledger-green/20'
           : 'text-text-2 hover:text-text hover:bg-surface2'
         }`
      }
    >
      <span className="text-base leading-none">{icon}</span>
      {label}
    </NavLink>
  )
}
