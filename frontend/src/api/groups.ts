import { api } from './client'
import type {
  ApiSuccess,
  Group,
  Member,
  CreateGroupPayload,
} from '@/types'

export const groupsApi = {
  list: async (): Promise<Group[]> => {
    const res = await api.get<ApiSuccess<Group[]>>('/groups/')
    return res.data.data
  },

  get: async (groupId: number): Promise<Group> => {
    const res = await api.get<ApiSuccess<Group>>(`/groups/${groupId}`)
    return res.data.data
  },

  create: async (payload: CreateGroupPayload): Promise<Group> => {
    const res = await api.post<ApiSuccess<Group>>('/groups/', payload)
    return res.data.data
  },

   members: async (groupId: number): Promise<Member[]> => {
        // The backend returns the members list inside the main group payload.
        // We fetch the group, extract the members array, and map the 'id' to 'user_id'
        // to match what the frontend components expect.
        const res = await api.get<ApiSuccess<any>>(`/groups/${groupId}`)

        return res.data.data.members.map((m: any) => ({
          user_id: m.id,
          username: m.username,
          email: m.email,
          joined_at: new Date().toISOString() // Stubbed, since backend omits this in the list
        }))
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
