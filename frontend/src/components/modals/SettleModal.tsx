import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Modal } from '@/components/ui/Modal'
import { FormField } from '@/components/ui/FormField'
import { Spinner } from '@/components/ui/Spinner'
import { createSettlementSchema, type CreateSettlementForm } from '@/schemas'
import type { Member } from '@/types'
import { useEffect } from 'react'

interface SettleModalProps {
  open:            boolean
  onClose:         () => void
  onSubmit:        (data: CreateSettlementForm) => Promise<void>
  members:         Member[]
  currentUserId:   number
  prefillUserId?:  number
  prefillAmount?:  string
  isLoading?:      boolean
}

export function SettleModal({
  open, onClose, onSubmit, members, currentUserId,
  prefillUserId, prefillAmount, isLoading,
}: SettleModalProps) {
  const eligible = members.filter(m => m.user_id !== currentUserId)

  const {
    register, handleSubmit, reset, setValue,
    formState: { errors },
  } = useForm<CreateSettlementForm>({
    resolver: zodResolver(createSettlementSchema),
    defaultValues: {
      paid_to_user_id: prefillUserId ?? (eligible[0]?.user_id ?? 0),
      amount:          prefillAmount ?? '',
    },
  })

  useEffect(() => {
    if (open) {
      setValue('paid_to_user_id', prefillUserId ?? (eligible[0]?.user_id ?? 0))
      setValue('amount', prefillAmount ?? '')
    }
  }, [open, prefillUserId, prefillAmount, eligible, setValue])

  const handleClose = () => { reset(); onClose() }

  return (
    <Modal open={open} onClose={handleClose} title="Record Settlement">
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        <FormField label="Paying to" error={errors.paid_to_user_id?.message} required>
          <select
            {...register('paid_to_user_id', { valueAsNumber: true })}
            className="input"
          >
            {eligible.map(m => (
              <option key={m.user_id} value={m.user_id}>{m.username}</option>
            ))}
          </select>
        </FormField>

        <FormField label="Amount" error={errors.amount?.message} required>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-text-3 text-sm">$</span>
            <input
              {...register('amount')}
              className={`input pl-7 ${errors.amount ? 'input-error' : ''}`}
              placeholder="0.00"
              inputMode="decimal"
            />
          </div>
        </FormField>

        <p className="text-xs text-text-3 bg-surface2 rounded-lg px-3 py-2.5 border border-border">
          This records a payment you made outside SplitLedger (cash, bank transfer, etc.).
        </p>

        <div className="flex gap-3 pt-2">
          <button type="button" onClick={handleClose} className="btn-md btn-ghost flex-1">
            Cancel
          </button>
          <button type="submit" disabled={isLoading} className="btn-md btn-primary flex-1">
            {isLoading ? <Spinner size="sm" /> : 'Record Payment'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
