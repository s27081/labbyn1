export interface ApiSearchItem {
  id: number
  label: string
  sublabel: string
  target_url: string
}

export interface ApiSearchList {
  machines: Array<ApiSearchItem>
  users: Array<ApiSearchItem>
  racks: Array<ApiSearchItem>
  teams: Array<ApiSearchItem>
  rooms: Array<ApiSearchItem>
  inventory: Array<ApiSearchItem>
  documentation: Array<ApiSearchItem>
}

export type ApiSearchResponse = ApiSearchList
