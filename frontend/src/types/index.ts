// ─────────────────────────────────────────────────────────────────────────────
// SplitLedger — TypeScript Types
// Mirror the backend models and API response shapes exactly.
// All monetary amounts are strings (the backend serialises Decimal as string).
// ─────────────────────────────────────────────────────────────────────────────

// ── Primitives ────────────────────────────────────────────────────────────────

/** A monetary amount serialised by the backend. Always a decimal string, e.g. "42.50" */
export type MoneyString = string

/** ISO-8601 datetime string from the backend */
export type ISODateTime = string

// ── Enums ─────────────────────────────────────────────────────────────────────

export type SplitMode = 'equal' | 'custom'

export type Category =
  | 'food'
  | 'transport'
  | 'accommodation'
  | 'entertainment'
  | 'utilities'
  | 'other'

export const CATEGORIES: { value: Category; label: string; emoji: string }[] = [
  { value: 'food',          label: 'Food & Drink',    emoji: '🍽️' },
  { value: 'transport',     label: 'Transport',        emoji: '🚗' },
  { value: 'accommodation', label: 'Accommodation',    emoji: '🏨' },
  { value: 'entertainment', label: 'Entertainment',    emoji: '🎬' },
  { value: 'utilities',     label: 'Utilities',        emoji: '💡' },
  { value: 'other',         label: 'Other',            emoji: '📦' },
]

export function categoryMeta(cat: Category) {
  return CATEGORIES.find(c => c.value === cat) ?? CATEGORIES[5]
}

// ── Domain models ─────────────────────────────────────────────────────────────

export interface User {
  id:         number
  username:   string
  email:      string
  created_at: ISODateTime
}

export interface Group {
  id:         number
  name:       string
  owner_id:   number
  created_at: ISODateTime
}

export interface Member {
  user_id:    number
  username:   string
  email:      string
  joined_at:  ISODateTime
}

export interface Split {
  user_id:    number
  username:   string
  amount:     MoneyString
}

export interface Expense {
  id:              number
  group_id:        number
  paid_by_user_id: number
  paid_by_username: string
  description:     string
  amount:          MoneyString
  split_mode:      SplitMode
  category:        Category
  splits:          Split[]
  created_at:      ISODateTime
  updated_at:      ISODateTime | null
  deleted_at:      ISODateTime | null
}

export interface Settlement {
  id:               number
  group_id:         number
  paid_by_user_id:  number
  paid_by_username: string
  paid_to_user_id:  number
  paid_to_username: string
  amount:           MoneyString
  created_at:       ISODateTime
}

export interface BalanceEntry {
  user_id:  number
  name:     string
  balance:  MoneyString
}

export interface SimplifiedDebt {
  from_user_id: number
  from_name:    string
  to_user_id:   number
  to_name:      string
  amount:       MoneyString
}

export interface GroupBalances {
  group_id:         number
  balances:         BalanceEntry[]
  simplified_debts: SimplifiedDebt[]
  balance_sum:      MoneyString
}

// ── API envelope ──────────────────────────────────────────────────────────────

export interface ApiSuccess<T> {
  data:     T
  warnings: Warning[]
}

export interface Warning {
  code:    string
  message: string
}

export interface ApiError {
  error: {
    code:    string
    message: string
    field?:  string
  }
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export interface AuthTokens {
  access_token:  string
  refresh_token: string
}

export interface AuthResponse {
  user:          User
  access_token:  string
  refresh_token: string
}

// ── Request payloads ──────────────────────────────────────────────────────────

export interface RegisterPayload {
  username: string
  email:    string
  password: string
}

export interface LoginPayload {
  username: string
  password: string
}

export interface CreateGroupPayload {
  name: string
}

export interface AddMemberPayload {
  user_id: number
}

export interface SplitInput {
  user_id: number
  amount:  string   // string to avoid float precision issues
}

export interface CreateExpensePayload {
  paid_by_user_id: number
  description:     string
  amount:          string
  split_mode:      SplitMode
  category?:       Category
  splits?:         SplitInput[]
}

export interface PatchExpensePayload {
  description?: string
  amount?:      string
  split_mode?:  SplitMode
  category?:    Category
  splits?:      SplitInput[]
}

export interface CreateSettlementPayload {
  paid_to_user_id: number
  amount:          string
}

// ── Derived / UI helpers ──────────────────────────────────────────────────────

/** Parse a MoneyString to a float for comparison / sign checks only.
 *  Never use this for arithmetic — only for UI sign detection. */
export function moneyFloat(m: MoneyString): number {
  return parseFloat(m)
}

export function moneySign(m: MoneyString): 'positive' | 'negative' | 'zero' {
  const n = moneyFloat(m)
  if (n > 0)  return 'positive'
  if (n < 0)  return 'negative'
  return 'zero'
}

export function formatMoney(m: MoneyString, opts?: { showSign?: boolean }): string {
  const n = Math.abs(moneyFloat(m))
  const formatted = n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  if (opts?.showSign) {
    const sign = moneyFloat(m) >= 0 ? '+' : '-'
    return `${sign}$${formatted}`
  }
  return `$${formatted}`
}
