import apiClient from './index'

export interface IPLookupRequest {
  ip_address: string
}

export interface IPLookupResult {
  target_ip: string
  found: boolean
  mac_address?: string
  switch_id?: number
  switch_name?: string
  switch_ip?: string
  port_name?: string
  vlan_id?: number
  query_time_ms: number
  message?: string
}

export interface IPLookupResponse {
  success: boolean
  result?: IPLookupResult
  error?: string
}

export interface QueryHistoryItem {
  id: number
  target_ip: string
  found_mac?: string
  switch_id?: number
  port_name?: string
  vlan_id?: number
  query_status: 'success' | 'not_found' | 'error'
  error_message?: string
  query_time_ms?: number
  queried_at: string
}

export interface QueryHistoryListResponse {
  total: number
  page: number
  page_size: number
  items: QueryHistoryItem[]
}

export const lookupApi = {
  // Lookup an IP address
  lookupIP: async (ipAddress: string): Promise<IPLookupResponse> => {
    const response = await apiClient.post('/api/v1/lookup/ip', {
      ip_address: ipAddress
    })
    return response.data
  },

  // Get query history
  getHistory: async (page: number = 1, pageSize: number = 20): Promise<QueryHistoryListResponse> => {
    const response = await apiClient.get('/api/v1/history', {
      params: { page, page_size: pageSize }
    })
    return response.data
  },

  // Get specific history item
  getHistoryItem: async (id: number): Promise<QueryHistoryItem> => {
    const response = await apiClient.get(`/api/v1/history/${id}`)
    return response.data
  }
}
