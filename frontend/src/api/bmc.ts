import apiClient, { API_BASE_URL } from './index'

export interface BMCServer {
  id: number
  name: string
  host: string
  username: string
  use_global_credentials: boolean
  credential_profile_id: number | null
  credential_profile_name: string | null
  enabled: boolean
  notes: string | null
  last_reset_at: string | null
  last_reset_result: string | null
  serial_number: string | null
  bmc_firmware_version: string | null
  bmc_info_updated_at: string | null
  verified: boolean
  verify_error: string | null
  created_at: string
  updated_at: string
}

export interface BMCServerListResponse {
  items: BMCServer[]
  total: number
}

export interface BMCServerCreate {
  name: string
  host: string
  username: string
  password?: string
  use_global_credentials: boolean
  credential_profile_id?: number
  enabled: boolean
  notes?: string
}

export interface BMCServerUpdate {
  name?: string
  host?: string
  username?: string
  password?: string
  use_global_credentials?: boolean
  credential_profile_id?: number
  enabled?: boolean
  notes?: string
}

export interface BMCResetHistory {
  id: number
  bmc_server_id: number
  server_name: string
  server_host: string
  status: 'success' | 'failure'
  error_category: string | null
  error_message: string | null
  attempts_made: number
  duration_ms: number | null
  ipmi_command: string | null
  triggered_by: string
  created_at: string
}

export interface BMCResetHistoryListResponse {
  items: BMCResetHistory[]
  total: number
}

export interface BMCResetStartResponse {
  session_id: string
  message: string
  total_servers: number
}

export interface BMCResetStatus {
  running: boolean
  session_id: string | null
  current_phase: string
  phase_label: string
  message: string | null
  error: string | null
  current_server_index: number
  total_servers: number
  completed_servers: number
  success_count: number
  failure_count: number
  current_server_name: string | null
  current_server_host: string | null
  current_attempt: number
  current_interface: string | null
  results: BMCResetServerResult[]
  started_at: string | null
  updated_at: string
  last_completed_at: string | null
}

export interface BMCResetServerResult {
  server_id: number
  server_name: string
  server_host: string
  status: 'success' | 'failure'
  error_category: string | null
  error_message: string | null
  attempts_made: number
  duration_ms: number
}

export interface BMCGlobalCredentials {
  username: string
  password_set: boolean
}

export const bmcApi = {
  async getServers(params?: { skip?: number; limit?: number; enabled_only?: boolean; verified?: boolean; search?: string }) {
    const { data } = await apiClient.get<BMCServerListResponse>('/api/v1/bmc/servers', { params })
    return data
  },

  async createServer(serverData: BMCServerCreate) {
    const { data } = await apiClient.post<BMCServer>('/api/v1/bmc/servers', serverData)
    return data
  },

  async updateServer(id: number, serverData: BMCServerUpdate) {
    const { data } = await apiClient.put<BMCServer>(`/api/v1/bmc/servers/${id}`, serverData)
    return data
  },

  async deleteServer(id: number) {
    await apiClient.delete(`/api/v1/bmc/servers/${id}`)
  },

  async getResetHistory(params?: { server_id?: number; status?: string; skip?: number; limit?: number }) {
    const { data } = await apiClient.get<BMCResetHistoryListResponse>('/api/v1/bmc/history', { params })
    return data
  },

  async startReset(serverIds: number[]) {
    const { data } = await apiClient.post<BMCResetStartResponse>('/api/v1/bmc/reset', { server_ids: serverIds })
    return data
  },

  async getResetStatus() {
    const { data } = await apiClient.get<BMCResetStatus>('/api/v1/bmc/reset-status')
    return data
  },

  getResetEventsUrl() {
    return `${API_BASE_URL}/api/v1/bmc/reset-events`
  },

  async getGlobalCredentials() {
    const { data } = await apiClient.get<BMCGlobalCredentials>('/api/v1/bmc/settings/credentials')
    return data
  },

  async updateGlobalCredentials(creds: { username: string; password?: string }) {
    await apiClient.put('/api/v1/bmc/settings/credentials', creds)
  },

  async getScheduleSettings() {
    const { data } = await apiClient.get('/api/v1/bmc/settings/schedule')
    return data as { enabled: boolean; day: number; hour: number; timeout: number }
  },

  async updateScheduleSetting(key: string, value: any) {
    await apiClient.put('/api/v1/bmc/settings/schedule', { [key]: value })
  },

  async getCredentialProfiles() {
    const { data } = await apiClient.get<BMCCredentialProfile[]>('/api/v1/bmc/settings/profiles')
    return data
  },

  async createCredentialProfile(profile: BMCCredentialProfileCreate) {
    const { data } = await apiClient.post<BMCCredentialProfile>('/api/v1/bmc/settings/profiles', profile)
    return data
  },

  async updateCredentialProfile(id: number, profile: BMCCredentialProfileUpdate) {
    const { data } = await apiClient.put<BMCCredentialProfile>(`/api/v1/bmc/settings/profiles/${id}`, profile)
    return data
  },

  async deleteCredentialProfile(id: number) {
    await apiClient.delete(`/api/v1/bmc/settings/profiles/${id}`)
  },

  async queryBMCInfo(serverId: number) {
    const { data } = await apiClient.post(`/api/v1/bmc/servers/${serverId}/query-info`)
    return data as { message: string; server_id: number }
  },

  async batchImportServers(req: BMCBatchImportRequest) {
    const { data } = await apiClient.post('/api/v1/bmc/servers/batch-import', req)
    return data as BMCBatchImportResult
  },
}

export interface BMCInfo {
  server_id: number
  serial_number: string | null
  bmc_firmware_version: string | null
  product_name: string | null
  manufacturer: string | null
  fru_raw: string | null
  mc_info_raw: string | null
}

export interface BMCBatchImportRequest {
  ip_start?: string
  ip_end?: string
  ips?: string
  username: string
  password?: string
  use_global_credentials: boolean
  credential_profile_id?: number
  enabled: boolean
}

export interface BMCBatchImportResult {
  total: number
  created: number
  skipped: number
  errors: string[]
  servers: BMCServer[]
}

export interface BMCCredentialProfile {
  id: number
  name: string
  username: string
  password_set: boolean
  server_count: number
  created_at: string
  updated_at: string
}

export interface BMCCredentialProfileCreate {
  name: string
  username: string
  password?: string
}

export interface BMCCredentialProfileUpdate {
  name?: string
  username?: string
  password?: string
}
