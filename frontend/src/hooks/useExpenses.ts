import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { expensesApi } from '@/api/expenses'
import { extractApiError } from '@/api/client'
import toast from 'react-hot-toast'
import type { CreateExpensePayload, PatchExpensePayload, Category } from '@/types'

export const expenseKeys = {
  list:     (groupId: number, cat?: Category) => ['expenses', groupId, cat] as const,
  detail:   (id: number)    => ['expenses', id] as const,
  balances: (groupId: number, cat?: Category) => ['balances', groupId, cat] as const,
}

export function useExpenses(groupId: number, category?: Category) {
  return useQuery({
    queryKey: expenseKeys.list(groupId, category),
    queryFn:  () => expensesApi.list(groupId, category ? { category } : undefined),
    enabled:  !!groupId,
  })
}

export function useBalances(groupId: number, category?: Category) {
  return useQuery({
    queryKey: expenseKeys.balances(groupId, category),
    queryFn:  () => expensesApi.balances(groupId, category ? { category } : undefined),
    enabled:  !!groupId,
  })
}

export function useCreateExpense(groupId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: CreateExpensePayload) => expensesApi.create(groupId, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['expenses', groupId] })
      qc.invalidateQueries({ queryKey: ['balances', groupId] })
      toast.success('Expense added')
    },
    onError: (err) => toast.error(extractApiError(err).message),
  })
}

export function useUpdateExpense(groupId: number) {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, payload }: { id: number; payload: any }) => {
      // Using axios directly to hit our new PUT route
      const { data } = await api.put(`/api/v1/groups/${groupId}/expenses/${id}`, payload);
      return data;
    },
    onSuccess: () => {
      // Refresh the lists instantly
      qc.invalidateQueries({ queryKey: ['expenses', groupId] });
      qc.invalidateQueries({ queryKey: ['balances', groupId] });
      toast.success('Expense updated!'); // Added the green success toast!
    },
    onError: (err) => {
      toast.error(extractApiError(err).message);
    }
  });
}

export function usePatchExpense(groupId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: PatchExpensePayload }) =>
      expensesApi.patch(id, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['expenses', groupId] })
      qc.invalidateQueries({ queryKey: ['balances', groupId] })
      toast.success('Expense updated')
    },
    onError: (err) => toast.error(extractApiError(err).message),
  })
}

export function useDeleteExpense(groupId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => expensesApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['expenses', groupId] })
      qc.invalidateQueries({ queryKey: ['balances', groupId] })
      toast.success('Expense deleted')
    },
    onError: (err) => toast.error(extractApiError(err).message),
  })
}
