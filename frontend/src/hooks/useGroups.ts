import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { groupsApi } from '@/api/groups'
import { extractApiError } from '@/api/client'
import toast from 'react-hot-toast'
import type { CreateGroupPayload } from '@/types'

// ── Query keys ────────────────────────────────────────────────────────────────

export const groupKeys = {
  all:     ['groups'] as const,
  detail:  (id: number) => ['groups', id] as const,
  members: (id: number) => ['groups', id, 'members'] as const,
}

// ── Queries ───────────────────────────────────────────────────────────────────

export function useGroups() {
  return useQuery({
    queryKey: groupKeys.all,
    queryFn:  groupsApi.list,
  })
}

export function useGroup(groupId: number) {
  return useQuery({
    queryKey: groupKeys.detail(groupId),
    queryFn:  () => groupsApi.get(groupId),
    enabled:  !!groupId,
  })
}

export function useGroupMembers(groupId: number) {
  return useQuery({
    queryKey: groupKeys.members(groupId),
    queryFn:  () => groupsApi.members(groupId),
    enabled:  !!groupId,
  })
}

// ── Mutations ─────────────────────────────────────────────────────────────────

export function useCreateGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: CreateGroupPayload) => groupsApi.create(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: groupKeys.all })
      toast.success('Group created')
    },
    onError: (err) => {
      toast.error(extractApiError(err).message)
    },
  })
}

export function useAddMember(groupId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (userId: number) => groupsApi.addMember(groupId, userId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: groupKeys.members(groupId) })
      toast.success('Member added')
    },
    onError: (err) => {
      toast.error(extractApiError(err).message)
    },
  })
}
