import { api } from './client'
import type {
  ApiSuccess,
  Expense,
  GroupBalances,
  CreateExpensePayload,
  PatchExpensePayload,
  Category,
} from '@/types'

export const expensesApi = {
  list: async (groupId: number, params?: { category?: Category }): Promise<Expense[]> => {
    const res = await api.get<ApiSuccess<Expense[]>>(`/groups/${groupId}/expenses`, {
      params,
    })
    return res.data.data
  },

  get: async (expenseId: number): Promise<Expense> => {
    const res = await api.get<ApiSuccess<Expense>>(`/expenses/${expenseId}`)
    return res.data.data
  },

  create: async (groupId: number, payload: CreateExpensePayload): Promise<Expense> => {
    const res = await api.post<ApiSuccess<Expense>>(
      `/groups/${groupId}/expenses`,
      payload,
    )
    return res.data.data
  },

  patch: async (expenseId: number, payload: PatchExpensePayload): Promise<Expense> => {
    const res = await api.patch<ApiSuccess<Expense>>(
      `/expenses/${expenseId}`,
      payload,
    )
    return res.data.data
  },

  delete: async (expenseId: number): Promise<void> => {
    await api.delete(`/expenses/${expenseId}`)
  },

  balances: async (groupId: number, params?: { category?: Category }): Promise<GroupBalances> => {
    const res = await api.get<ApiSuccess<GroupBalances>>(
      `/groups/${groupId}/balances`,
      { params },
    )
    return res.data.data
  },
}
