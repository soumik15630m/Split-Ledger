import { api } from './client'
import type {
  ApiSuccess,
  Settlement,
  CreateSettlementPayload,
  Warning,
} from '@/types'

export interface CreateSettlementResult {
  settlement: Settlement
  warnings:   Warning[]
}

export const settlementsApi = {
  list: async (groupId: number): Promise<Settlement[]> => {
    const res = await api.get<ApiSuccess<Settlement[]>>(
      `/groups/${groupId}/settlements`,
    )
    return res.data.data
  },

  create: async (
    groupId: number,
    payload: CreateSettlementPayload,
  ): Promise<CreateSettlementResult> => {
    const res = await api.post<ApiSuccess<Settlement>>(
      `/groups/${groupId}/settlements`,
      payload,
    )
    return {
      settlement: res.data.data,
      warnings:   res.data.warnings ?? [],
    }
  },
}
