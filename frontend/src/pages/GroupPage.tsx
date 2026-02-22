import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import { useGroup, useGroupMembers, useAddMember } from '@/hooks/useGroups'
import { useExpenses, useBalances, useCreateExpense, useDeleteExpense } from '@/hooks/useExpenses'
import { useSettlements, useCreateSettlement } from '@/hooks/useSettlements'
import { ExpenseCard } from '@/components/ExpenseCard'
import { BalancePanel } from '@/components/BalancePanel'
import { Avatar } from '@/components/ui/Avatar'
import { MoneyDisplay } from '@/components/ui/MoneyDisplay'
import { Spinner } from '@/components/ui/Spinner'
import { EmptyState } from '@/components/ui/EmptyState'
import { AddExpenseModal } from '@/components/modals/AddExpenseModal'
import { SettleModal } from '@/components/modals/SettleModal'
import { AddMemberModal } from '@/components/modals/AddMemberModal'
import type { CreateExpenseForm } from '@/schemas'
import type { CreateSettlementPayload, Expense } from '@/types'

type Tab = 'expenses' | 'balances' | 'settlements' | 'members'

export function GroupPage() {
  const { id }       = useParams<{ id: string }>()
  const groupId      = Number(id)
  const { user }     = useAuth()

  const [tab, setTab]                     = useState<Tab>('expenses')
  const [showAddExpense, setAddExpense]    = useState(false)
  const [showSettle, setShowSettle]        = useState(false)
  const [showAddMember, setShowAddMember]  = useState(false)
  const [settlePreset, setSettlePreset]    = useState<{ userId: number; amount: string } | null>(null)
  const [_editExpense, setEditExpense]     = useState<Expense | null>(null)

  // Queries
  const { data: group,      isLoading: groupLoading }    = useGroup(groupId)
  const { data: members,    isLoading: membersLoading }  = useGroupMembers(groupId)
  const { data: expenses,   isLoading: expLoading }      = useExpenses(groupId)
  const { data: balances,   isLoading: balLoading }      = useBalances(groupId)
  const { data: settlements, isLoading: setLoading }     = useSettlements(groupId)

  // Mutations
  const createExpense    = useCreateExpense(groupId)
  const deleteExpense    = useDeleteExpense(groupId)
  const createSettlement = useCreateSettlement(groupId)
  const addMember        = useAddMember(groupId)

  if (groupLoading) {
    return (
      <div className="flex items-center justify-center py-32">
        <Spinner size="lg" />
      </div>
    )
  }

  if (!group) {
    return (
      <div className="max-w-2xl mx-auto px-6 py-16 text-center">
        <p className="text-text-2">Group not found</p>
        <Link to="/dashboard" className="btn-link text-sm mt-4 inline-block">← Back</Link>
      </div>
    )
  }

  // ── Handlers ─────────────────────────────────────────────────────────────

  const handleCreateExpense = async (form: CreateExpenseForm) => {
    const payload = {
      paid_by_user_id: form.paid_by_user_id,
      description:     form.description,
      amount:          form.amount,
      split_mode:      form.split_mode,
      category:        form.category,
      splits: form.split_mode === 'custom'
        ? form.splits?.map(s => ({ user_id: s.user_id, amount: s.amount }))
        : undefined,
    }
    await createExpense.mutateAsync(payload)
    setAddExpense(false)
  }

  const handleSettle = async (form: { paid_to_user_id: number; amount: string }) => {
    const payload: CreateSettlementPayload = {
      paid_to_user_id: form.paid_to_user_id,
      amount:          form.amount,
    }
    await createSettlement.mutateAsync(payload)
    setShowSettle(false)
    setSettlePreset(null)
  }

  const openSettlePreset = (toUserId: number, _toUsername: string, amount: string) => {
    setSettlePreset({ userId: toUserId, amount })
    setShowSettle(true)
  }

  const TABS: { key: Tab; label: string }[] = [
    { key: 'expenses',    label: 'Expenses' },
    { key: 'balances',    label: 'Balances' },
    { key: 'settlements', label: 'Payments' },
    { key: 'members',     label: 'Members' },
  ]

  return (
    <div className="max-w-2xl mx-auto px-6 py-8 animate-fade-in">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="mb-6">
        <Link
          to="/dashboard"
          className="text-xs text-text-3 hover:text-text-2 transition-colors mb-3 inline-block"
        >
          ← All Groups
        </Link>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="font-display text-3xl text-text">{group.name}</h1>
            <p className="text-sm text-text-3 mt-1">
              {members?.length ?? 0} member{members?.length !== 1 ? 's' : ''}
              {balances && (
                <> · Balance sum: <span className="font-mono">{balances.balance_sum}</span></>
              )}
            </p>
          </div>
          {/* Quick actions */}
          <div className="flex gap-2 shrink-0">
            <button onClick={() => setAddExpense(true)} className="btn-md btn-primary">
              + Expense
            </button>
            <button onClick={() => setShowSettle(true)} className="btn-md btn-ghost">
              Settle
            </button>
          </div>
        </div>
      </div>

      {/* ── Tabs ───────────────────────────────────────────────────────── */}
      <div className="flex gap-6 border-b border-border mb-6">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`tab-item ${tab === t.key ? 'active' : ''}`}
          >
            {t.label}
            {t.key === 'expenses' && expenses && (
              <span className="ml-2 font-mono text-xs text-text-3">
                {expenses.filter(e => !e.deleted_at).length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── Tab content ────────────────────────────────────────────────── */}

      {/* Expenses */}
      {tab === 'expenses' && (
        <div className="space-y-2 animate-fade-in">
          {expLoading ? (
            <div className="flex justify-center py-10"><Spinner /></div>
          ) : !expenses?.filter(e => !e.deleted_at).length ? (
            <EmptyState
              icon="🧾"
              title="No expenses yet"
              subtitle="Add the first expense to start tracking."
              action={
                <button onClick={() => setAddExpense(true)} className="btn-md btn-primary">
                  + Add Expense
                </button>
              }
            />
          ) : (
            expenses
              .filter(e => !e.deleted_at)
              .map(expense => (
                <ExpenseCard
                  key={expense.id}
                  expense={expense}
                  onDelete={id => deleteExpense.mutate(id)}
                  onEdit={setEditExpense}
                />
              ))
          )}
        </div>
      )}

      {/* Balances */}
      {tab === 'balances' && (
        <div className="animate-fade-in">
          {balLoading ? (
            <div className="flex justify-center py-10"><Spinner /></div>
          ) : balances ? (
            <BalancePanel
              data={balances}
              currentUserId={user?.id}
              onSettle={openSettlePreset}
            />
          ) : null}
        </div>
      )}

      {/* Settlements */}
      {tab === 'settlements' && (
        <div className="space-y-2 animate-fade-in">
          {setLoading ? (
            <div className="flex justify-center py-10"><Spinner /></div>
          ) : !settlements?.length ? (
            <EmptyState
              icon="💸"
              title="No payments yet"
              subtitle="Settle up and record payments here."
              action={
                <button onClick={() => setShowSettle(true)} className="btn-md btn-primary">
                  Record Payment
                </button>
              }
            />
          ) : (
            settlements.map(s => (
              <div key={s.id}
                className="card flex items-center gap-3 px-4 py-3">
                <Avatar name={s.paid_by_username} size="sm" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-text">
                    <span className="font-medium">{s.paid_by_username}</span>
                    <span className="text-text-3 mx-2">paid</span>
                    <span className="font-medium">{s.paid_to_username}</span>
                  </p>
                  <p className="text-xs text-text-3 mt-0.5">
                    {new Date(s.created_at).toLocaleDateString('en-US', {
                      month: 'short', day: 'numeric', year: 'numeric',
                    })}
                  </p>
                </div>
                <MoneyDisplay amount={s.amount} neutral size="sm" />
              </div>
            ))
          )}
        </div>
      )}

      {/* Members */}
      {tab === 'members' && (
        <div className="animate-fade-in">
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm text-text-2">
              {members?.length ?? 0} member{members?.length !== 1 ? 's' : ''}
            </p>
            {user?.id === group.owner_id && (
              <button
                onClick={() => setShowAddMember(true)}
                className="btn-sm btn-ghost"
              >
                + Add Member
              </button>
            )}
          </div>
          {membersLoading ? (
            <div className="flex justify-center py-10"><Spinner /></div>
          ) : (
            <div className="space-y-2">
              {members?.map(m => (
                <div key={m.user_id}
                  className="card flex items-center gap-3 px-4 py-3">
                  <Avatar name={m.username} size="md" />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-text">{m.username}</p>
                    <p className="text-xs text-text-3">{m.email}</p>
                  </div>
                  {m.user_id === group.owner_id && (
                    <span className="badge-green text-xs">owner</span>
                  )}
                  {m.user_id === user?.id && m.user_id !== group.owner_id && (
                    <span className="badge-gray text-xs">you</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Modals ─────────────────────────────────────────────────────── */}
      {members && user && (
        <>
          <AddExpenseModal
            open={showAddExpense}
            onClose={() => setAddExpense(false)}
            onSubmit={handleCreateExpense}
            members={members}
            currentUserId={user.id}
            isLoading={createExpense.isPending}
          />
          <SettleModal
            open={showSettle}
            onClose={() => { setShowSettle(false); setSettlePreset(null) }}
            onSubmit={handleSettle}
            members={members}
            currentUserId={user.id}
            prefillUserId={settlePreset?.userId}
            prefillAmount={settlePreset?.amount}
            isLoading={createSettlement.isPending}
          />
          <AddMemberModal
            open={showAddMember}
            onClose={() => setShowAddMember(false)}
            onAdd={async (userId) => {
              await addMember.mutateAsync(userId)
              setShowAddMember(false)
            }}
            isLoading={addMember.isPending}
          />
        </>
      )}
    </div>
  )
}
