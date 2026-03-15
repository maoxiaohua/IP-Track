import apiClient from './index'

export interface Switch {
  id: number
  name: string
  ip_address: string
  vendor: 'cisco' | 'dell' | 'alcatel' | 'juniper'
  model?: string
  enabled: boolean

  // CLI fields
  cli_enabled: boolean
  ssh_port?: number
  username?: string
  connection_timeout?: number

  // Ping status
  is_reachable?: boolean | null
  last_check_at?: string | null
  response_time_ms?: number | null

  // Data collection
  auto_collect_arp: boolean
  auto_collect_mac: boolean
  last_arp_collection_at?: string | null
  last_mac_collection_at?: string | null
  last_collection_status?: string | null
  last_collection_message?: string | null

  // SNMP fields
  snmp_enabled: boolean
  snmp_version?: string
  snmp_port?: number
  snmp_username?: string
  snmp_auth_protocol?: string
  snmp_priv_protocol?: string
  has_snmp_credentials?: boolean

  created_at: string
  updated_at: string
}

export interface SwitchCreate {
  name: string
  ip_address: string
  vendor: 'cisco' | 'dell' | 'alcatel' | 'juniper'
  model?: string
  enabled?: boolean

  // CLI fields
  cli_enabled?: boolean
  ssh_port?: number
  username?: string
  password?: string
  enable_password?: string
  connection_timeout?: number

  // Data collection
  auto_collect_arp?: boolean
  auto_collect_mac?: boolean

  // SNMP fields (required)
  snmp_enabled?: boolean
  snmp_version?: string
  snmp_port?: number
  snmp_username: string
  snmp_auth_protocol?: string
  snmp_auth_password: string
  snmp_priv_protocol?: string
  snmp_priv_password: string
  snmp_community?: string
}

export interface SwitchUpdate {
  name?: string
  ip_address?: string
  vendor?: 'cisco' | 'dell' | 'alcatel' | 'juniper'
  model?: string
  cli_enabled?: boolean
  ssh_port?: number
  username?: string
  password?: string
  enable_password?: string
  connection_timeout?: number
  enabled?: boolean

  // Data collection
  auto_collect_arp?: boolean
  auto_collect_mac?: boolean

  // SNMP fields
  snmp_enabled?: boolean
  snmp_version?: string
  snmp_port?: number
  snmp_username?: string
  snmp_auth_protocol?: string
  snmp_auth_password?: string
  snmp_priv_protocol?: string
  snmp_priv_password?: string
  snmp_community?: string
}

export interface SwitchTestResponse {
  success: boolean
  message: string
  details?: any
}

export interface SwitchListParams {
  skip?: number
  limit?: number
  search?: string
}

export interface SwitchListResponse {
  items: Switch[]
  total: number
}

export const switchesApi = {
  // Get all switches
  list: async (params?: SwitchListParams): Promise<SwitchListResponse> => {
    const queryParams = new URLSearchParams()
    if (params?.skip !== undefined) queryParams.append('skip', params.skip.toString())
    if (params?.limit !== undefined) queryParams.append('limit', params.limit.toString())
    if (params?.search) queryParams.append('search', params.search)

    const url = `/api/v1/switches${queryParams.toString() ? '?' + queryParams.toString() : ''}`
    const response = await apiClient.get(url)
    return response.data
  },

  // Get a specific switch
  get: async (id: number): Promise<Switch> => {
    const response = await apiClient.get(`/api/v1/switches/${id}`)
    return response.data
  },

  // Create a new switch
  create: async (data: SwitchCreate): Promise<Switch> => {
    const response = await apiClient.post('/api/v1/switches', data)
    return response.data
  },

  // Update a switch
  update: async (id: number, data: SwitchUpdate): Promise<Switch> => {
    const response = await apiClient.put(`/api/v1/switches/${id}`, data)
    return response.data
  },

  // Delete a switch
  delete: async (id: number): Promise<void> => {
    await apiClient.delete(`/api/v1/switches/${id}`)
  },

  // Test switch connection
  test: async (id: number): Promise<SwitchTestResponse> => {
    const response = await apiClient.post(`/api/v1/switches/${id}/test`)
    return response.data
  },

  // Ping a switch
  ping: async (id: number): Promise<any> => {
    const response = await apiClient.post(`/api/v1/switches/${id}/ping`)
    return response.data
  },

  // Ping all switches
  pingAll: async (): Promise<any> => {
    const response = await apiClient.post('/api/v1/switches/ping-all')
    return response.data
  },

  // Manual collection operations
  collectArp: async (id: number): Promise<any> => {
    const response = await apiClient.post(`/api/v1/switches/${id}/collect/arp`)
    return response.data
  },

  collectMac: async (id: number): Promise<any> => {
    const response = await apiClient.post(`/api/v1/switches/${id}/collect/mac`)
    return response.data
  },

  collectDeviceInfo: async (id: number): Promise<any> => {
    const response = await apiClient.post(`/api/v1/switches/${id}/collect/device-info`)
    return response.data
  },

  // Get optical modules
  getOpticalModules: async (id: number): Promise<any> => {
    const response = await apiClient.get(`/api/v1/switches/${id}/optical-modules`)
    return response.data
  },

  // Collect optical modules
  collectOpticalModules: async (id: number): Promise<any> => {
    const response = await apiClient.post(`/api/v1/switches/${id}/collect/optical-modules`)
    return response.data
  }
}
