import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiUpdateRack } from './racks.types'
import api from '@/lib/api'

const PATHS = {
  BASE: '/db/racks',
  DETAIL: (id: number) => `/db/racks/${id}`,
}

export async function useCreateRackMutation(rackData: {
  name: string
  room_id: number
  team_id: number
  tag_ids?: Array<string>
}) {
  const { data } = await api.post(PATHS.BASE, rackData)
  return data
}

export const useDeletRackMutation = (rackId: string | number) => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationKey: ['delete-rack'],
    mutationFn: () => api.delete(PATHS.DETAIL(rackId)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['racks'] })
    },
  })
}

export const useUpdateRackMutation = (rackId: string | number) => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationKey: ['update-rack'],
    mutationFn: (rackData: ApiUpdateRack) =>
      api.patch(PATHS.DETAIL(rackId), rackData),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['racks'] })
    },
  })
}
