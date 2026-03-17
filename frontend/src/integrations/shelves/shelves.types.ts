export interface ApiShelfItem {
  id: number
  name: string
  order: number
  rack_id: number
  rack_name: string
  machines: Array<ApiShelfMachineItem>
}

export interface ApiShelfMachineItem {
  id: number
  name: string
  ip_address: string
  mac_address: string
  team_id: number
  machine_url: string | null
}

export interface ApiShelfCreate {
  name: string
  order: number
}

export type ApiShelvesResponse = Array<ApiShelfItem>
