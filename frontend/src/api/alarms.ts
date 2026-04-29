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
  current_switch_is_reachable?: boolean | null
  current_switch_collection_status?: string | null
  current_switch_collection_message?: string | null
  current_freshness_status?: 'fresh' | 'stale' | null
  current_freshness_warning?: string | null
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

export interface SwitchAlarmGroup {
  switch_id: number
  switch_name: string
  switch_ip?: string | null
  active_count: number
  acknowledged_count: number
  resolved_count: number
  open_count: number
  total_alarm_records: number
  total_occurrences: number
  highest_active_severity?: string | null
  latest_alarm_id?: number | null
  latest_alarm_title?: string | null
  latest_alarm_message?: string | null
  latest_alarm_status?: string | null
  latest_event_at?: string | null
  current_switch_is_reachable?: boolean | null
  current_switch_collection_status?: string | null
  current_switch_collection_message?: string | null
  current_freshness_status?: 'fresh' | 'stale' | null
  current_freshness_warning?: string | null
}

export interface SwitchAlarmGroupListResponse {
  items: SwitchAlarmGroup[]
  total: number
}

export interface SwitchAlarmTimelineEvent {
  timestamp: string
  event_type: 'created' | 'reoccurred' | 'acknowledged' | 'resolved' | 'auto_resolved' | string
  alarm_id: number
  severity: string
  status: string
  title: string
  message: string
  occurrence_count: number
  actor?: string | null
  note?: string | null
  details?: any | null
}

export interface SwitchAlarmTimeline {
  switch_id: number
  switch_name: string
  switch_ip?: string | null
  active_count: number
  acknowledged_count: number
  resolved_count: number
  open_count: number
  total_alarm_records: number
  total_occurrences: number
  current_switch_is_reachable?: boolean | null
  current_switch_collection_status?: string | null
  current_switch_collection_message?: string | null
  current_freshness_status?: 'fresh' | 'stale' | null
  current_freshness_warning?: string | null
  events: SwitchAlarmTimelineEvent[]
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
  },

  getSwitchGroups: async (limit: number = 100): Promise<SwitchAlarmGroupListResponse> => {
    const response = await apiClient.get('/api/v1/alarms/switch-groups', {
      params: { limit }
    })
    return response.data
  },

  getSwitchTimeline: async (switchId: number, limit: number = 200): Promise<SwitchAlarmTimeline> => {
    const response = await apiClient.get(`/api/v1/alarms/switches/${switchId}/timeline`, {
      params: { limit }
    })
    return response.data
  }
}
