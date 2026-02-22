import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { settlementsApi } from '@/api/settlements'
import { extractApiError } from '@/api/client'
import toast from 'react-hot-toast'
import type { CreateSettlementPayload } from '@/types'

export const settlementKeys = {
  list: (groupId: number) => ['settlements', groupId] as const,
}

export function useSettlements(groupId: number) {
  return useQuery({
    queryKey: settlementKeys.list(groupId),
    queryFn:  () => settlementsApi.list(groupId),
    enabled:  !!groupId,
  })
}

export function useCreateSettlement(groupId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: CreateSettlementPayload) =>
      settlementsApi.create(groupId, payload),
    onSuccess: ({ warnings }) => {
      qc.invalidateQueries({ queryKey: settlementKeys.list(groupId) })
      qc.invalidateQueries({ queryKey: ['balances', groupId] })
      if (warnings.length > 0) {
        toast.success(`Payment recorded — note: ${warnings[0].message}`, { duration: 5000 })
      } else {
        toast.success('Payment recorded')
      }
    },
    onError: (err) => toast.error(extractApiError(err).message),
  })
}
