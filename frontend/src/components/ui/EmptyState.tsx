import type { ReactNode } from 'react'

interface EmptyStateProps {
  icon:      string
  title:     string
  subtitle?: string
  action?:   ReactNode
}

export function EmptyState({ icon, title, subtitle, action }: EmptyStateProps) {
  return (
    <div className="empty-state animate-fade-in">
      <span className="empty-state-icon text-5xl">{icon}</span>
      <p className="empty-state-title">{title}</p>
      {subtitle && <p className="empty-state-sub">{subtitle}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
