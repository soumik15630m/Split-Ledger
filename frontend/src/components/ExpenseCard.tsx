import { useState } from 'react'
import { Avatar } from '@/components/ui/Avatar'
import { MoneyDisplay } from '@/components/ui/MoneyDisplay'
import { categoryMeta } from '@/types'
import type { Expense } from '@/types'
import { useAuth } from '@/auth/AuthContext'
import clsx from 'clsx'

interface ExpenseCardProps {
  expense:    Expense
  onDelete?:  (id: number) => void
  onEdit?:    (expense: Expense) => void
  className?: string
}

export function ExpenseCard({ expense, onDelete, onEdit, className }: ExpenseCardProps) {
  const { user }       = useAuth()
  const [open, setOpen] = useState(false)
  const meta           = categoryMeta(expense.category)
  const isDeleted      = !!expense.deleted_at
  const canAct         = !isDeleted && (user?.id === expense.paid_by_user_id)

  return (
    <div
      className={clsx(
        'card transition-all duration-200',
        isDeleted ? 'opacity-50 grayscale' : 'hover:border-border-strong',
        className,
      )}
    >
      {/* Main row */}
      <div
        className="flex items-start gap-3 p-4 cursor-pointer"
        onClick={() => setOpen(v => !v)}
      >
        {/* Category icon */}
        <div className="w-9 h-9 rounded-lg bg-surface2 border border-border
                        flex items-center justify-center text-base shrink-0 mt-0.5">
          {meta.emoji}
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2">
            <p className={clsx('text-sm font-medium truncate', isDeleted ? 'line-through' : 'text-text')}>
              {expense.description}
            </p>
            <span className="badge-gray text-xs shrink-0">{meta.label}</span>
          </div>
          <p className="text-xs text-text-3 mt-0.5">
            Paid by{' '}
            <span className="text-text-2 font-medium">{expense.paid_by_username}</span>
            {' · '}
            {new Date(expense.created_at).toLocaleDateString('en-US', {
              month: 'short', day: 'numeric',
            })}
          </p>
        </div>

        {/* Amount */}
        <div className="text-right shrink-0">
          <MoneyDisplay amount={expense.amount} neutral size="sm" />
          <p className="text-xs text-text-3 mt-0.5 font-mono">
            {expense.split_mode}
          </p>
        </div>

        {/* Chevron */}
        <span className={clsx(
          'text-text-3 text-xs transition-transform duration-200 mt-1 shrink-0',
          open && 'rotate-180',
        )}>
          ▾
        </span>
      </div>

      {/* Expanded splits */}
      {open && (
        <div className="border-t border-border animate-slide-down">
          <div className="px-4 py-3 space-y-2">
            <p className="text-xs font-medium text-text-3 uppercase tracking-wide mb-2">
              Split breakdown
            </p>
            {expense.splits?.map(split => (
              <div key={split.user_id} className="flex items-center gap-2">
                <Avatar name={split.username} size="xs" />
                <span className="text-sm text-text-2 flex-1">{split.username}</span>
                <MoneyDisplay amount={split.amount} neutral size="xs" />
              </div>
            ))}
          </div>

          {/* Actions */}
          {canAct && (onEdit || onDelete) && (
            <div className="border-t border-border px-4 py-2.5 flex gap-2">
              {onEdit && (
                <button
                  onClick={e => { e.stopPropagation(); onEdit(expense) }}
                  className="btn-sm btn-ghost flex-1"
                >
                  Edit
                </button>
              )}
              {onDelete && (
                <button
                  onClick={e => { e.stopPropagation(); onDelete(expense.id) }}
                  className="btn-sm btn-danger flex-1"
                >
                  Delete
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
