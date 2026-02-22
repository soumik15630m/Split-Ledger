import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useGroups, useCreateGroup } from '@/hooks/useGroups'
import { Modal } from '@/components/ui/Modal'
import { FormField } from '@/components/ui/FormField'
import { Spinner } from '@/components/ui/Spinner'
import { EmptyState } from '@/components/ui/EmptyState'
import { createGroupSchema, type CreateGroupForm } from '@/schemas'
import type { Group } from '@/types'

export function DashboardPage() {
  const { data: groups, isLoading } = useGroups()
  const createMutation              = useCreateGroup()
  const [showCreate, setShowCreate] = useState(false)

  const {
    register, handleSubmit, reset,
    formState: { errors, isSubmitting },
  } = useForm<CreateGroupForm>({ resolver: zodResolver(createGroupSchema) })

  const onCreate = async (data: CreateGroupForm) => {
    await createMutation.mutateAsync(data)
    reset()
    setShowCreate(false)
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-10">
      {/* Header */}
      <div className="flex items-end justify-between mb-8">
        <div>
          <h1 className="font-display text-3xl text-text">Your Groups</h1>
          <p className="text-sm text-text-3 mt-1">
            Track shared expenses across trips, houses, and events
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="btn-md btn-primary"
        >
          + New Group
        </button>
      </div>

      {/* Groups grid */}
      {isLoading ? (
        <div className="flex justify-center py-20">
          <Spinner size="lg" />
        </div>
      ) : !groups?.length ? (
        <EmptyState
          icon="⬡"
          title="No groups yet"
          subtitle="Create your first group to start tracking shared expenses."
          action={
            <button onClick={() => setShowCreate(true)} className="btn-md btn-primary">
              Create a Group
            </button>
          }
        />
      ) : (
        <div className="space-y-3 animate-fade-in">
          {groups.map(group => (
            <GroupCard key={group.id} group={group} />
          ))}
        </div>
      )}

      {/* Create modal */}
      <Modal open={showCreate} onClose={() => { setShowCreate(false); reset() }} title="New Group">
        <form onSubmit={handleSubmit(onCreate)} className="space-y-4">
          <FormField label="Group Name" error={errors.name?.message} required>
            <input
              {...register('name')}
              className={`input ${errors.name ? 'input-error' : ''}`}
              placeholder="Barcelona Trip, House 3B, Team Lunch…"
              autoFocus
            />
          </FormField>
          <div className="flex gap-3 pt-2">
            <button type="button" onClick={() => { setShowCreate(false); reset() }}
              className="btn-md btn-ghost flex-1">
              Cancel
            </button>
            <button type="submit" disabled={isSubmitting} className="btn-md btn-primary flex-1">
              {isSubmitting ? <Spinner size="sm" /> : 'Create Group'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  )
}

function GroupCard({ group }: { group: Group }) {
  return (
    <Link
      to={`/groups/${group.id}`}
      className="card-hover flex items-center gap-4 px-5 py-4 block"
    >
      {/* Icon */}
      <div className="w-10 h-10 rounded-xl bg-surface2 border border-border
                      flex items-center justify-center text-lg shrink-0">
        ⬡
      </div>
      {/* Info */}
      <div className="flex-1 min-w-0">
        <p className="font-medium text-text">{group.name}</p>
        <p className="text-xs text-text-3 mt-0.5">
          Created {new Date(group.created_at).toLocaleDateString('en-US', {
            year: 'numeric', month: 'short', day: 'numeric',
          })}
        </p>
      </div>
      <span className="text-text-3 text-sm">→</span>
    </Link>
  )
}
