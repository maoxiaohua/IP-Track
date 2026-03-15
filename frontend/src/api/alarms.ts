import apiClient from './index'

export enum AlarmSeverity {
  CRITICAL = 'critical',
  ERROR = 'error',
  WARNING = 'warning',
  INFO = 'info'
}

export enum AlarmStatus {
  ACTIVE = 'active',
  ACKNOWLEDGED = 'acknowledged',
  RESOLVED = 'resolved',
  AUTO_RESOLVED = 'auto_resolved'
}

export enum AlarmSourceType {
  COLLECTION = 'collection',
  SWITCH = 'switch',
  BATCH = 'batch',
  SYSTEM = 'system'
}

export interface Alarm {
  id: number
  severity: AlarmSeverity
  status: AlarmStatus
  title: string
  message: string
  source_type: AlarmSourceType
  source_id?: number | null
  source_name?: string | null
  details?: any | null
  fingerprint: string
  occurrence_count: number
  created_at: string
  last_occurrence_at: string
  acknowledged_at?: string | null
  acknowledged_by?: string | null
  resolved_at?: string | null
  resolved_by?: string | null
}

export interface AlarmListParams {
  skip?: number
  limit?: number
  severity?: string
  status?: string
  source_type?: string
}

export interface AlarmListResponse {
  items: Alarm[]
  total: number
}

export interface AlarmStats {
  total_active: number
  total_acknowledged: number
  total_resolved: number
  by_severity: Record<string, number>
  by_source_type: Record<string, number>
  top_failing_switches?: Array<{
    switch_id: number
    switch_name: string
    alarm_count: number
  }>
}

export const alarmsApi = {
  // Get all alarms with filtering and pagination
  list: async (params?: AlarmListParams): Promise<AlarmListResponse> => {
    const queryParams = new URLSearchParams()
    if (params?.skip !== undefined) queryParams.append('skip', params.skip.toString())
    if (params?.limit !== undefined) queryParams.append('limit', params.limit.toString())
    if (params?.severity) queryParams.append('severity', params.severity)
    if (params?.status) queryParams.append('status', params.status)
    if (params?.source_type) queryParams.append('source_type', params.source_type)

    const url = `/api/v1/alarms${queryParams.toString() ? '?' + queryParams.toString() : ''}`
    const response = await apiClient.get(url)
    return response.data
  },

  // Get a specific alarm
  get: async (id: number): Promise<Alarm> => {
    const response = await apiClient.get(`/api/v1/alarms/${id}`)
    return response.data
  },

  // Acknowledge an alarm
  acknowledge: async (id: number): Promise<Alarm> => {
    const response = await apiClient.post(`/api/v1/alarms/${id}/acknowledge`)
    return response.data
  },

  // Resolve an alarm
  resolve: async (id: number): Promise<Alarm> => {
    const response = await apiClient.post(`/api/v1/alarms/${id}/resolve`)
    return response.data
  },

  // Delete an alarm
  delete: async (id: number): Promise<void> => {
    await apiClient.delete(`/api/v1/alarms/${id}`)
  },

  // Get alarm statistics
  getStats: async (): Promise<AlarmStats> => {
    const response = await apiClient.get('/api/v1/alarms/stats')
    return response.data
  }
}
