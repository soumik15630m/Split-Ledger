// ─────────────────────────────────────────────────────────────────────────────
// SplitLedger — Zod Validation Schemas
// Client-side form validation. Mirrors backend marshmallow schemas.
// ─────────────────────────────────────────────────────────────────────────────

import { z } from 'zod'

// ── Shared validators ─────────────────────────────────────────────────────────

/** Decimal string: positive, max 2dp. Matches backend INV-7. */
const moneyString = z
  .string()
  .min(1, 'Amount is required')
  .refine(v => /^\d+(\.\d{1,2})?$/.test(v.trim()), {
    message: 'Enter a valid amount (e.g. 12.50)',
  })
  .refine(v => parseFloat(v) > 0, { message: 'Amount must be greater than zero' })

const splitModeEnum = z.enum(['equal', 'custom'])

const categoryEnum = z.enum([
  'food', 'transport', 'accommodation', 'entertainment', 'utilities', 'other',
])

// ── Auth ──────────────────────────────────────────────────────────────────────

export const registerSchema = z.object({
  username: z
    .string()
    .min(3,  'Username must be at least 3 characters')
    .max(50, 'Username must be at most 50 characters')
    .regex(/^[a-zA-Z0-9_]+$/, 'Only letters, numbers, and underscores allowed'),
  email: z
    .string()
    .email('Enter a valid email address'),
  password: z
    .string()
    .min(8, 'Password must be at least 8 characters')
    .refine(v => /[a-zA-Z]/.test(v), { message: 'Password must contain at least one letter' })
    .refine(v => /[0-9]/.test(v),    { message: 'Password must contain at least one number' }),
})
export type RegisterForm = z.infer<typeof registerSchema>

export const loginSchema = z.object({
  username: z.string().min(1, 'Username is required'),
  password: z.string().min(1, 'Password is required'),
})
export type LoginForm = z.infer<typeof loginSchema>

// ── Groups ────────────────────────────────────────────────────────────────────

export const createGroupSchema = z.object({
  name: z
    .string()
    .min(1,   'Group name is required')
    .max(100, 'Group name must be at most 100 characters')
    .refine(v => v.trim().length > 0, { message: 'Group name cannot be empty' }),
})
export type CreateGroupForm = z.infer<typeof createGroupSchema>

export const addMemberSchema = z.object({
  username: z.string().min(1, 'Username is required'),
})
export type AddMemberForm = z.infer<typeof addMemberSchema>

// ── Expenses ──────────────────────────────────────────────────────────────────

export const splitInputSchema = z.object({
  user_id:  z.number().int().positive(),
  username: z.string(),
  amount:   moneyString,
})

export const createExpenseSchema = z
  .object({
    description:     z.string().min(1, 'Description is required').max(255),
    amount:          moneyString,
    split_mode:      splitModeEnum,
    category:        categoryEnum.default('other'),
    paid_by_user_id: z.number().int().positive('Select who paid'),
    splits:          z.array(splitInputSchema).optional(),
  })
  .superRefine((data, ctx) => {
    if (data.split_mode === 'custom') {
      if (!data.splits || data.splits.length === 0) {
        ctx.addIssue({ code: 'custom', path: ['splits'], message: 'Enter split amounts for each person' })
        return
      }
      // Client-side INV-1 check
      const total = data.splits.reduce((sum, s) => sum + parseFloat(s.amount || '0'), 0)
      const expected = parseFloat(data.amount || '0')
      if (Math.abs(total - expected) > 0.001) {
        ctx.addIssue({
          code: 'custom', path: ['splits'],
          message: `Split amounts must add up to $${expected.toFixed(2)} (currently $${total.toFixed(2)})`,
        })
      }
      // Duplicate user check
      const ids = data.splits.map(s => s.user_id)
      if (new Set(ids).size !== ids.length) {
        ctx.addIssue({ code: 'custom', path: ['splits'], message: 'Each person can only appear once' })
      }
    }
  })
export type CreateExpenseForm = z.infer<typeof createExpenseSchema>

export const patchExpenseSchema = z
  .object({
    description: z.string().min(1).max(255).optional(),
    amount:      moneyString.optional(),
    split_mode:  splitModeEnum.optional(),
    category:    categoryEnum.optional(),
    splits:      z.array(splitInputSchema).optional(),
  })
  .superRefine((data, ctx) => {
    // Rule D: amount and splits must be co-present (unless switching to equal)
    if (data.amount && data.split_mode !== 'equal' && !data.splits) {
      ctx.addIssue({ code: 'custom', path: ['splits'], message: 'Provide split amounts when changing the total' })
    }
  })
export type PatchExpenseForm = z.infer<typeof patchExpenseSchema>

// ── Settlements ───────────────────────────────────────────────────────────────

export const createSettlementSchema = z.object({
  paid_to_user_id: z.number().int().positive('Select who you are paying'),
  amount:          moneyString,
})
export type CreateSettlementForm = z.infer<typeof createSettlementSchema>
