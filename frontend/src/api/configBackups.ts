import apiClient from './index'

export type BackupStatus = 'never' | 'running' | 'success' | 'failed' | 'unsupported' | 'skipped'

export interface BackupOverviewItem {
  switch_id: number
  name: string
  ip_address: string | null
  vendor: string
  model: string | null
  location: string | null
  enabled: boolean
  cli_enabled: boolean
  backup_enabled: boolean
  backup_interval_minutes: number | null
  backup_device_type: string | null
  backup_config_command: string | null
  // 网络不可达：计划备份已暂停，恢复可达后自动继续
  backup_unreachable: boolean
  interval_minutes: number
  supported: boolean
  unsupported_reason: string | null
  status: BackupStatus
  message: string | null
  trigger_source: string | null
  last_backup_at: string | null
  last_duration_ms: number | null
  last_success_at: string | null
  last_success_id: number | null
  last_success_size: number | null
  last_sha256: string | null
  version_count: number
}

export interface BackupOverviewResponse {
  items: BackupOverviewItem[]
  total: number
  global_interval_minutes: number
}

export interface BackupRecord {
  id: number
  switch_id: number
  status: BackupStatus
  trigger_source: string
  sha256: string | null
  size_bytes: number | null
  device_type: string | null
  command: string | null
  message: string | null
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
}

export interface BackupHistoryResponse {
  items: BackupRecord[]
  total: number
  page: number
  page_size: number
}

export interface BackupVersionContent extends BackupRecord {
  content: string
}

export interface BackupDiffResponse {
  from: BackupRecord
  to: BackupRecord
  diff: string
  truncated: boolean
}

export interface BackupGlobalSettings {
  interval_minutes: number
  retention_versions: number
  vendor_presets?: Record<string, { device_type: string; command: string }>
}

export interface SwitchBackupSettingsPayload {
  backup_enabled?: boolean
  backup_interval_minutes?: number | null
  backup_device_type?: string | null
  backup_config_command?: string | null
}

export interface SwitchBackupSettingsResponse {
  switch_id: number
  backup_enabled: boolean
  backup_interval_minutes: number | null
  backup_device_type: string | null
  backup_config_command: string | null
  resolved_device_type: string | null
  resolved_command: string | null
  unsupported_reason: string | null
}

export interface RunBackupResult {
  status: string
  message: string
  backup_id: number | null
  sha256?: string
  size_bytes?: number
  duration_ms?: number
}

export const fetchBackupOverview = async (status?: string): Promise<BackupOverviewResponse> => {
  const response = await apiClient.get('/api/v1/config-backups', {
    params: status ? { status } : undefined
  })
  return response.data
}

export const runBackupNow = async (switchId: number): Promise<RunBackupResult> => {
  const response = await apiClient.post(`/api/v1/config-backups/${switchId}/run`)
  return response.data
}

export const fetchBackupHistory = async (
  switchId: number,
  params: { page?: number; page_size?: number; status?: string } = {}
): Promise<BackupHistoryResponse> => {
  const response = await apiClient.get(`/api/v1/config-backups/${switchId}/history`, { params })
  return response.data
}

export const fetchBackupContent = async (backupId: number): Promise<BackupVersionContent> => {
  const response = await apiClient.get(`/api/v1/config-backups/versions/${backupId}/content`)
  return response.data
}

export const fetchBackupDiff = async (fromId: number, toId: number): Promise<BackupDiffResponse> => {
  const response = await apiClient.get('/api/v1/config-backups/diff', {
    params: { from_id: fromId, to_id: toId }
  })
  return response.data
}

export const fetchBackupGlobalSettings = async (): Promise<BackupGlobalSettings> => {
  const response = await apiClient.get('/api/v1/config-backups/settings')
  return response.data
}

export const updateBackupGlobalSettings = async (
  payload: { interval_minutes: number; retention_versions: number }
): Promise<BackupGlobalSettings> => {
  const response = await apiClient.put('/api/v1/config-backups/settings', payload)
  return response.data
}

export const updateSwitchBackupSettings = async (
  switchId: number,
  payload: SwitchBackupSettingsPayload
): Promise<SwitchBackupSettingsResponse> => {
  const response = await apiClient.put(`/api/v1/config-backups/${switchId}/settings`, payload)
  return response.data
}

// 下载配置：后端返回 attachment，这里转成浏览器下载
export const downloadBackup = async (backupId: number, fallbackName = 'config.cfg'): Promise<void> => {
  const response = await apiClient.get(`/api/v1/config-backups/versions/${backupId}/download`, {
    responseType: 'blob'
  })
  const disposition: string = response.headers?.['content-disposition'] || ''
  const match = /filename\*=UTF-8''([^;]+)/i.exec(disposition) || /filename="?([^";]+)"?/i.exec(disposition)
  const filename = match ? decodeURIComponent(match[1]) : fallbackName
  const url = window.URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)
}
