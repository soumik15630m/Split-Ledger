import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Modal } from '@/components/ui/Modal'
import { FormField } from '@/components/ui/FormField'
import { Spinner } from '@/components/ui/Spinner'
import { addMemberSchema, type AddMemberForm } from '@/schemas'
import { api, extractApiError } from '@/api/client'
import type { ApiSuccess, User } from '@/types'
import toast from 'react-hot-toast'

interface AddMemberModalProps {
  open:       boolean
  onClose:    () => void
  onAdd:      (userId: number) => Promise<void>
  isLoading?: boolean
}

export function AddMemberModal({ open, onClose, onAdd, isLoading }: AddMemberModalProps) {
  const [resolvedUser, setResolvedUser] = useState<User | null>(null)
  const [resolving,    setResolving]    = useState(false)

  const {
    register, handleSubmit, watch, reset,
    formState: { errors },
  } = useForm<AddMemberForm>({ resolver: zodResolver(addMemberSchema) })

  const username = watch('username')

  const lookupUser = async () => {
    if (!username?.trim()) return
    setResolving(true)
    try {
      // The backend exposes GET /users?username=X (or similar — adjust if route differs)
      const res = await api.get<ApiSuccess<User>>(`/users/by-username/${username.trim()}`)
      setResolvedUser(res.data.data)
    } catch (err) {
      const e = extractApiError(err)
      toast.error(e.code === 'NOT_FOUND' ? `User "${username}" not found` : e.message)
      setResolvedUser(null)
    } finally {
      setResolving(false)
    }
  }

  const handleAdd = async () => {
    if (!resolvedUser) return
    await onAdd(resolvedUser.id)
    reset()
    setResolvedUser(null)
  }

  const handleClose = () => { reset(); setResolvedUser(null); onClose() }

  return (
    <Modal open={open} onClose={handleClose} title="Add Member">
      <div className="space-y-4">
        <FormField label="Username" error={errors.username?.message} required>
          <div className="flex gap-2">
            <input
              {...register('username')}
              className="input flex-1"
              placeholder="their username"
              onKeyDown={e => e.key === 'Enter' && lookupUser()}
            />
            <button
              type="button"
              onClick={lookupUser}
              disabled={resolving}
              className="btn-md btn-ghost shrink-0"
            >
              {resolving ? <Spinner size="sm" /> : 'Find'}
            </button>
          </div>
        </FormField>

        {resolvedUser && (
          <div className="flex items-center gap-3 p-3 rounded-lg bg-ledger-green/5
                          border border-ledger-green/20 animate-fade-in">
            <div className="w-8 h-8 rounded-full bg-ledger-green/20 flex items-center
                            justify-center text-ledger-green font-mono font-bold text-sm">
              {resolvedUser.username.slice(0, 2).toUpperCase()}
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium text-text">{resolvedUser.username}</p>
              <p className="text-xs text-text-3">{resolvedUser.email}</p>
            </div>
            <span className="text-ledger-green text-lg">✓</span>
          </div>
        )}

        <div className="flex gap-3 pt-2">
          <button type="button" onClick={handleClose} className="btn-md btn-ghost flex-1">
            Cancel
          </button>
          <button
            type="button"
            disabled={!resolvedUser || isLoading}
            onClick={handleAdd}
            className="btn-md btn-primary flex-1"
          >
            {isLoading ? <Spinner size="sm" /> : 'Add to Group'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
