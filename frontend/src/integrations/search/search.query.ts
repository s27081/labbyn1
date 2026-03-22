import { queryOptions } from '@tanstack/react-query'
import type { ApiSearchResponse } from './search.types'
import api from '@/lib/api'

const PATHS = {
  BASE: '/db/search',
}

export const searchListQueryOptions = queryOptions({
  queryKey: ['search'],
  queryFn: async () => {
    const { data } = await api.get<ApiSearchResponse>(PATHS.BASE)
    return data
  },
})
