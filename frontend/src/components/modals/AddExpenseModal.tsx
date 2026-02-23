import { useEffect } from 'react'
import { useForm, useFieldArray, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Modal } from '@/components/ui/Modal'
import { FormField } from '@/components/ui/FormField'
import { Spinner } from '@/components/ui/Spinner'
import { createExpenseSchema, type CreateExpenseForm } from '@/schemas'
import { CATEGORIES } from '@/types'
import type { Member, Expense } from '@/types'

interface AddExpenseModalProps {
  open:       boolean
  onClose:    () => void
  onSubmit:   (data: CreateExpenseForm) => Promise<void>
  onUpdate?:  (id: number, data: CreateExpenseForm) => Promise<void>
  members:    Member[]
  currentUserId: number
  isLoading?: boolean
  expenseToEdit?: Expense | null
}

export function AddExpenseModal({
                                  open, onClose, onSubmit, onUpdate, members, currentUserId, isLoading, expenseToEdit
                                }: AddExpenseModalProps) {
  const {
    register, control, handleSubmit, watch, setValue, reset,
    formState: { errors },
  } = useForm<CreateExpenseForm>({
    resolver: zodResolver(createExpenseSchema),
    defaultValues: {
      split_mode: 'equal',
      category:   'other',
      paid_by_user_id: currentUserId,
    },
  })

  const splitMode  = watch('split_mode')
  const amount     = watch('amount')

  const { fields, replace } = useFieldArray({ control, name: 'splits' as never })

  // 1. Pre-fill form when editing, or reset to defaults when opening as "Add"
  useEffect(() => {
    if (open) {
      if (expenseToEdit) {
        reset({
          description: expenseToEdit.description,
          amount: expenseToEdit.amount,
          category: expenseToEdit.category,
          paid_by_user_id: expenseToEdit.paid_by_user_id,
          split_mode: expenseToEdit.split_mode,
          splits: expenseToEdit.splits?.map(s => ({
            user_id: s.user_id,
            username: s.username, // keeping username for the UI display
            amount: s.amount
          })) || []
        })
      } else {
        reset({
          split_mode: 'equal',
          category: 'other',
          paid_by_user_id: currentUserId,
        })
      }
    }
  }, [open, expenseToEdit, reset, currentUserId])

  // Debugging: If submit doesn't work, this will log the validation errors to your console!
  useEffect(() => {
    if (Object.keys(errors).length > 0) {
      console.log("Form Validation Errors preventing submit:", errors)
    }
  }, [errors])

  // Smart Auto-distribute: Keeps manual entries and distributes the leftover
  const autoSplit = () => {
    if (!amount) return;

    const total = parseFloat(amount);
    const currentSplits = watch('splits') || [];

    // Identify empty vs filled fields
    const emptyFields = currentSplits.filter(s => !s.amount || s.amount === '' || parseFloat(s.amount) === 0);
    const filledFields = currentSplits.filter(s => s.amount && s.amount !== '' && parseFloat(s.amount) > 0);

    const totalFilled = filledFields.reduce((sum, s) => sum + parseFloat(s.amount), 0);
    const leftover = total - totalFilled;

    // Scenario A: Full Reset (If no boxes are empty, or math is negative)
    if (emptyFields.length === 0 || leftover <= 0) {
      const n = members.length;
      const base = Math.floor((total / n) * 100) / 100;
      let pennies = Math.round((total - base * n) * 100);

      replace(members.map((m) => {
        let amt = base;
        if (pennies > 0) {
          amt += 0.01; // Drop extra pennies on the first people
          pennies--;
        }
        return { user_id: m.user_id, username: m.username, amount: amt.toFixed(2) };
      }));
      return;
    }

    // Scenario B: Smart Distribute Leftover
    const nEmpty = emptyFields.length;
    const baseLeftover = Math.floor((leftover / nEmpty) * 100) / 100;
    let leftoverPennies = Math.round((leftover - baseLeftover * nEmpty) * 100);

    const updatedValues = currentSplits.map(s => {
      // If the box is empty, give them a share of the leftover
      if (!s.amount || s.amount === '' || parseFloat(s.amount) === 0) {
        let amt = baseLeftover;
        if (leftoverPennies > 0) {
          amt += 0.01; // Drop extra pennies
          leftoverPennies--;
        }
        return { ...s, amount: amt.toFixed(2) };
      }
      // Keep the manually typed values (like your 125)
      return s;
    });

    replace(updatedValues);
  }

  const handleClose = () => {
    reset()
    onClose()
  }

  // 2. Route the submit to either Create or Update
  const handleFormSubmit = async (data: CreateExpenseForm) => {
    if (expenseToEdit) {
      if (!onUpdate) {
        console.error("CRITICAL: onUpdate function is missing!");
        return; // Stop the form from doing anything if the function is missing
      }
      console.log("Sending UPDATE request for ID:", expenseToEdit.id);
      await onUpdate(expenseToEdit.id, data);
    } else {
      console.log("Sending CREATE request");
      await onSubmit(data);
    }
  }

  const isEditing = !!expenseToEdit

  return (
      <Modal open={open} onClose={handleClose} title={isEditing ? "Edit Expense" : "Add Expense"}>
        <form onSubmit={handleSubmit(handleFormSubmit)} className="space-y-4">
          {/* Description */}
          <FormField label="Description" error={errors.description?.message} required>
            <input
                {...register('description')}
                className={`input ${errors.description ? 'input-error' : ''}`}
                placeholder="Dinner at Barça, Airbnb deposit…"
            />
          </FormField>

          {/* Amount + Category */}
          <div className="grid grid-cols-2 gap-3">
            <FormField label="Amount" error={errors.amount?.message} required>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-text-3 font-mono text-sm">$</span>
                <input
                    {...register('amount')}
                    className={`input pl-7 ${errors.amount ? 'input-error' : ''}`}
                    placeholder="0.00"
                    inputMode="decimal"
                />
              </div>
            </FormField>

            <FormField label="Category" error={errors.category?.message}>
              <select {...register('category')} className="input">
                {CATEGORIES.map(c => (
                    <option key={c.value} value={c.value}>
                      {c.emoji} {c.label}
                    </option>
                ))}
              </select>
            </FormField>
          </div>

          {/* Paid by */}
          <FormField label="Paid by" error={errors.paid_by_user_id?.message} required>
            <select {...register('paid_by_user_id', { valueAsNumber: true })} className="input">
              {members.map(m => (
                  <option key={m.user_id} value={m.user_id}>{m.username}</option>
              ))}
            </select>
          </FormField>

          {/* Split mode */}
          <FormField label="Split type">
            <div className="flex gap-2">
              {(['equal', 'custom'] as const).map(mode => (
                  <button
                      key={mode}
                      type="button"
                      onClick={() => {
                        setValue('split_mode', mode)
                        // Only initialize empty fields if clicking "Custom" manually AND fields are currently empty
                        if (mode === 'custom' && fields.length === 0) {
                          replace(members.map(m => ({ user_id: m.user_id, username: m.username, amount: '' })))
                        }
                      }}
                      className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-all
                  ${splitMode === mode
                          ? 'bg-ledger-green/10 border-ledger-green/40 text-ledger-green'
                          : 'border-border text-text-2 hover:border-border-strong'
                      }`}
                  >
                    {mode === 'equal' ? '= Equal' : '✎ Custom'}
                  </button>
              ))}
            </div>
          </FormField>

          {/* Custom splits */}
          {splitMode === 'custom' && (
              <div className="animate-slide-down">
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs font-medium text-text-3 uppercase tracking-wide">
                    Split amounts
                  </label>
                  <button type="button" onClick={autoSplit}
                          className="text-xs text-ledger-blue hover:text-blue-300 transition-colors">
                    Auto-distribute
                  </button>
                </div>
                <div className="space-y-2">
                  {fields.map((f, i) => (
                      <div key={f.id} className="flex items-center gap-3">
                  <span className="text-sm text-text-2 flex-1 font-medium">
                    {members[i]?.username}
                  </span>
                        <div className="relative w-32">
                          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-text-3 text-sm">$</span>
                          <Controller
                              control={control}
                              name={`splits.${i}.amount` as const}
                              render={({ field }) => (
                                  <input
                                      {...field}
                                      className="input pl-7 text-right"
                                      placeholder="0.00"
                                      inputMode="decimal"
                                  />
                              )}
                          />
                        </div>
                      </div>
                  ))}
                </div>
                {errors.splits && (
                    <p className="mt-2 text-xs text-ledger-red animate-fade-in">
                      {(errors.splits as { message?: string })?.message ?? 'Check split amounts'}
                    </p>
                )}
              </div>
          )}

          {/* Actions */}
          <div className="flex gap-3 pt-2">
            <button type="button" onClick={handleClose} className="btn-md btn-ghost flex-1">
              Cancel
            </button>
            <button type="submit" disabled={isLoading} className="btn-md btn-primary flex-1">
              {isLoading ? <Spinner size="sm" /> : (isEditing ? 'Save Changes' : 'Add Expense')}
            </button>
          </div>
        </form>
      </Modal>
  )
}