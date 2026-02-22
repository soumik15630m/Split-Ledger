import { Avatar } from '@/components/ui/Avatar'
import { MoneyDisplay } from '@/components/ui/MoneyDisplay'
import { EmptyState } from '@/components/ui/EmptyState'
import type { GroupBalances } from '@/types'
import { moneyFloat } from '@/types'

interface BalancePanelProps {
  data:        GroupBalances
  onSettle?:   (toUserId: number, toUsername: string, amount: string) => void
  currentUserId?: number
}

export function BalancePanel({ data, onSettle, currentUserId }: BalancePanelProps) {
  const nonZero = data.balances.filter(b => Math.abs(moneyFloat(b.balance)) >= 0.005)

  return (
    <div className="space-y-6">
      {/* Member balances */}
      <div>
        <h3 className="text-xs font-medium text-text-3 uppercase tracking-widest mb-3">
          Member Balances
        </h3>
        {nonZero.length === 0 ? (
          <EmptyState icon="✓" title="All square" subtitle="Nobody owes anything right now." />
        ) : (
          <div className="space-y-2">
            {data.balances.map(entry => (
              <div key={entry.user_id}
                className="flex items-center gap-3 py-2.5 px-3 rounded-lg hover:bg-surface2 transition-colors">
                <Avatar name={entry.name} size="sm" />
                <span className="flex-1 text-sm text-text">{entry.name}</span>
                <MoneyDisplay amount={entry.balance} showSign size="sm" />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Simplified debts */}
      {data.simplified_debts.length > 0 && (
        <div>
          <h3 className="text-xs font-medium text-text-3 uppercase tracking-widest mb-3">
            Suggested Settlements
          </h3>
          <div className="space-y-2">
            {data.simplified_debts.map((debt, i) => {
              const isMe = debt.from_user_id === currentUserId
              return (
                <div key={i}
                  className="flex items-center gap-3 p-3 rounded-lg border border-border">
                  <Avatar name={debt.from_name} size="sm" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-text">
                      <span className={isMe ? 'text-ledger-red font-medium' : ''}>
                        {debt.from_name}
                      </span>
                      <span className="text-text-3 mx-2">→</span>
                      <span>{debt.to_name}</span>
                    </p>
                  </div>
                  <MoneyDisplay amount={debt.amount} neutral size="sm" />
                  {isMe && onSettle && (
                    <button
                      onClick={() => onSettle(debt.to_user_id, debt.to_name, debt.amount)}
                      className="btn-sm btn-primary ml-2"
                    >
                      Settle
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
