import type { ApiTagsResponse } from '../tags/tags.types'
import api from '@/lib/api'

const PATHS = {
  BASE: '/db/rooms',
  DETAIL: (id: number) => `/db/rooms/${id}`,
}

export async function useCreateLabMutation(labData: {
  name: string
  room_type: string
  team_id: number
  tag_ids?: ApiTagsResponse
}) {
  const { data } = await api.post(PATHS.BASE, labData)
  return data
}
