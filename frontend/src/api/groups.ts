import { api } from './client'
import type {
  ApiSuccess,
  Group,
  Member,
  CreateGroupPayload,
} from '@/types'

export const groupsApi = {
  list: async (): Promise<Group[]> => {
    const res = await api.get<ApiSuccess<Group[]>>('/groups')
    return res.data.data
  },

  get: async (groupId: number): Promise<Group> => {
    const res = await api.get<ApiSuccess<Group>>(`/groups/${groupId}`)
    return res.data.data
  },

  create: async (payload: CreateGroupPayload): Promise<Group> => {
    const res = await api.post<ApiSuccess<Group>>('/groups', payload)
    return res.data.data
  },

  members: async (groupId: number): Promise<Member[]> => {
    const res = await api.get<ApiSuccess<Member[]>>(`/groups/${groupId}/members`)
    return res.data.data
  },

  /** Looks up user_id by username, then adds them */
  addMember: async (groupId: number, userId: number): Promise<Member> => {
    const res = await api.post<ApiSuccess<Member>>(
      `/groups/${groupId}/members`,
      { user_id: userId },
    )
    return res.data.data
  },

  removeMember: async (groupId: number, userId: number): Promise<void> => {
    await api.delete(`/groups/${groupId}/members/${userId}`)
  },
}
