import apiClient from './index'

export interface SNMPProfile {
  id: number
  name: string
  version: string
  username?: string
  auth_protocol?: string
  priv_protocol?: string
  port: number
  timeout: number
  retries: number
  description?: string
  enabled: boolean
  created_at: string
  updated_at: string
  subnet_count?: number
}

export interface SNMPProfileCreate {
  name: string
  version: string
  username?: string
  auth_protocol?: string
  auth_password?: string
  priv_protocol?: string
  priv_password?: string
  community?: string
  port?: number
  timeout?: number
  retries?: number
  description?: string
  enabled?: boolean
}

export interface SNMPProfileUpdate {
  name?: string
  version?: string
  username?: string
  auth_protocol?: string
  auth_password?: string
  priv_protocol?: string
  priv_password?: string
  community?: string
  port?: number
  timeout?: number
  retries?: number
  description?: string
  enabled?: boolean
}

export interface SNMPProfileListResponse {
  items: SNMPProfile[]
  total: number
  page: number
  page_size: number
}

export interface SNMPTestRequest {
  target_ip: string
  profile_id?: number
  username?: string
  auth_protocol?: string
  auth_password?: string
  priv_protocol?: string
  priv_password?: string
  community?: string
  version?: string
  port?: number
  timeout?: number
}

export interface SNMPTestResponse {
  success: boolean
  message: string
  data?: {
    system_name?: string
    contact?: string
    location?: string
    machine_type?: string
    vendor?: string
    last_boot_time?: string
  }
  error?: string
}

// Get all SNMP profiles
export const getSNMPProfiles = async (params?: {
  page?: number
  page_size?: number
  enabled_only?: boolean
}) => {
  const response = await apiClient.get<SNMPProfileListResponse>('/api/v1/snmp-profiles', { params })
  return response.data
}

// Get single SNMP profile
export const getSNMPProfile = async (id: number) => {
  const response = await apiClient.get<SNMPProfile>(`/api/v1/snmp-profiles/${id}`)
  return response.data
}

// Create SNMP profile
export const createSNMPProfile = async (data: SNMPProfileCreate) => {
  const response = await apiClient.post<SNMPProfile>('/api/v1/snmp-profiles', data)
  return response.data
}

// Update SNMP profile
export const updateSNMPProfile = async (id: number, data: SNMPProfileUpdate) => {
  const response = await apiClient.put<SNMPProfile>(`/api/v1/snmp-profiles/${id}`, data)
  return response.data
}

// Delete SNMP profile
export const deleteSNMPProfile = async (id: number) => {
  await apiClient.delete(`/api/v1/snmp-profiles/${id}`)
}

// Test SNMP connection
export const testSNMPConnection = async (data: SNMPTestRequest) => {
  const response = await apiClient.post<SNMPTestResponse>('/api/v1/snmp-profiles/test', data)
  return response.data
}
