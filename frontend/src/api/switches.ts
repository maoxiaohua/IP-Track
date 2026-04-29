import apiClient from './index'

export interface Switch {
  id: number
  name: string
  ip_address: string
  vendor: 'cisco' | 'dell' | 'alcatel' | 'juniper'
  model?: string
  role?: string
  priority?: number
  enabled: boolean

  // CLI fields
  cli_enabled: boolean
  cli_transport: 'ssh' | 'telnet'
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
  last_optical_collection_at?: string | null
  last_optical_success_at?: string | null
  last_collection_status?: string | null
  last_collection_message?: string | null
  last_optical_collection_status?: string | null
  last_optical_collection_message?: string | null
  last_optical_modules_count?: number | null
  trunk_review_completed: boolean
  trunk_review_completed_at?: string | null
  trunk_review_note?: string | null

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
  cli_transport?: 'ssh' | 'telnet'
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
  snmp_username?: string
  snmp_auth_protocol?: string
  snmp_auth_password?: string
  snmp_priv_protocol?: string
  snmp_priv_password?: string
  snmp_community?: string
}

export interface SwitchUpdate {
  name?: string
  ip_address?: string
  vendor?: 'cisco' | 'dell' | 'alcatel' | 'juniper'
  model?: string
  cli_enabled?: boolean
  cli_transport?: 'ssh' | 'telnet'
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
  trunk_review_completed?: boolean
  trunk_review_note?: string | null
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
  trunk_review_completed?: boolean
  sort_by?: 'name' | 'ip_address' | 'model' | 'last_collection_time' | 'connection_status'
  sort_order?: 'asc' | 'desc'
}

export interface SwitchListResponse {
  items: Switch[]
  total: number
}

export interface PortAnalysisEntry {
  port_name: string
  mac_count: number
  unique_vlans: number
  port_type: 'access' | 'trunk' | 'uplink' | 'unknown'
  confidence_score: number
  analyzed_at: string
  lookup_policy_override: 'include' | 'exclude' | null
  lookup_policy_note?: string | null
  lookup_policy_updated_at?: string | null
  effective_lookup_status: 'included' | 'excluded'
  effective_lookup_reason: string
  lookup_included: boolean
}

export interface PortAnalysisResponse {
  switch: {
    id: number
    name: string
    ip_address: string
  }
  freshness: {
    status: 'fresh' | 'stale'
    reason: string
    warning?: string | null
    last_analyzed_at?: string | null
    last_collection_attempt_at?: string | null
    last_collection_status?: string | null
    last_collection_message?: string | null
    is_reachable?: boolean | null
  }
  ports: PortAnalysisEntry[]
  summary: {
    total_ports: number
    access_ports: number
    trunk_ports: number
    uplink_ports: number
    unknown_ports: number
    lookup_included_ports: number
    lookup_excluded_ports: number
  }
}

export interface OpticalModuleEntry {
  id: number
  port_name: string
  module_type?: string | null
  model?: string | null
  serial_number?: string | null
  vendor?: string | null
  speed_gbps?: number | null
  collected_at?: string | null
  first_seen?: string | null
  last_seen?: string | null
  presence_status: 'present' | 'historical'
  is_present: boolean
  freshness_status: 'fresh' | 'stale'
  freshness_warning?: string | null
}

export interface OpticalInventoryFreshness {
  status: 'fresh' | 'stale'
  reason: string
  warning?: string | null
  last_optical_collection_at?: string | null
  last_optical_success_at?: string | null
  last_optical_collection_status?: string | null
  last_optical_collection_message?: string | null
  last_optical_modules_count?: number | null
  is_reachable?: boolean | null
}

export interface OpticalModuleResponse {
  switch_id: number
  switch_name: string
  switch_ip: string
  total_modules: number
  present_modules: number
  historical_modules: number
  freshness: OpticalInventoryFreshness
  entries: OpticalModuleEntry[]
}

export const switchesApi = {
  // Get all switches
  list: async (params?: SwitchListParams): Promise<SwitchListResponse> => {
    const queryParams = new URLSearchParams()
    if (params?.skip !== undefined) queryParams.append('skip', params.skip.toString())
    if (params?.limit !== undefined) queryParams.append('limit', params.limit.toString())
    if (params?.search) queryParams.append('search', params.search)
    if (params?.trunk_review_completed !== undefined) queryParams.append('trunk_review_completed', String(params.trunk_review_completed))
    if (params?.sort_by) queryParams.append('sort_by', params.sort_by)
    if (params?.sort_order) queryParams.append('sort_order', params.sort_order)

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
  getOpticalModules: async (id: number): Promise<OpticalModuleResponse> => {
    const response = await apiClient.get(`/api/v1/switches/${id}/optical-modules`)
    return response.data
  },

  // Collect optical modules
  collectOpticalModules: async (id: number): Promise<any> => {
    const response = await apiClient.post(`/api/v1/switches/${id}/collect/optical-modules`)
    return response.data
  },

  // Analyze switch ports from MAC table data
  analyzePorts: async (id: number): Promise<any> => {
    const response = await apiClient.post(`/api/v1/switches/${id}/analyze-ports`)
    return response.data
  },

  // Get per-port lookup policy state
  getPortAnalysis: async (id: number): Promise<PortAnalysisResponse> => {
    const response = await apiClient.get(`/api/v1/network/port-analysis/${id}`)
    return response.data
  },

  // Override whether a port participates in lookup matching
  updatePortLookupPolicy: async (
    id: number,
    data: {
      port_name: string
      lookup_policy_override: 'include' | 'exclude' | null
      lookup_policy_note?: string | null
    }
  ): Promise<PortAnalysisEntry> => {
    const response = await apiClient.put(`/api/v1/network/port-analysis/${id}/lookup-policy`, data)
    return response.data
  }
}
