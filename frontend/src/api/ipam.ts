import apiClient, { API_BASE_URL } from './index'

export interface IPAddressDetail {
  id: number
  ip_address: string
  status: string
  is_reachable: boolean
  response_time?: number
  hostname?: string
  hostname_source?: string
  dns_name?: string
  system_name?: string
  machine_type?: string
  vendor?: string
  contact?: string
  location?: string
  mac_address?: string
  os_type?: string
  os_name?: string
  os_version?: string
  os_vendor?: string
  switch_id?: number
  switch_name?: string
  switch_port?: string
  vlan_id?: number
  last_seen_at?: string
  last_boot_time?: string
  last_scan_at?: string
  description?: string
}

export interface IPScanHistory {
  id: number
  ip_address_id: number
  is_reachable: boolean
  response_time?: number
  hostname?: string
  mac_address?: string
  os_type?: string
  os_name?: string
  os_version?: string
  os_vendor?: string
  switch_id?: number
  switch_port?: string
  vlan_id?: number
  status_changed: boolean
  hostname_changed: boolean
  os_changed: boolean
  mac_changed: boolean
  switch_changed: boolean
  port_changed: boolean
  scanned_at: string
}

export interface IPAMScanSummary {
  subnet_id?: number
  subnet_last_scan_at?: string
  total_scanned?: number
  reachable?: number
  unreachable?: number
  new_devices?: number
  changed_devices?: number
  scan_duration?: number
}

export interface IPAMScanStatus {
  type?: string
  running: boolean
  session_id?: string
  source?: 'manual' | 'auto' | string
  scan_type?: 'quick' | 'full' | string
  current_phase: string
  phase_label: string
  message?: string
  error?: string
  subnet_id?: number
  subnet_name?: string
  subnet_network?: string
  current_subnet_index: number
  total_subnets: number
  completed_subnets: number
  current_subnet_total_ips: number
  current_subnet_completed_ips: number
  current_subnet_pending_ips: number
  current_subnet_reachable_ips: number
  current_subnet_unreachable_ips: number
  current_subnet_enrichment_total: number
  current_subnet_enrichment_completed: number
  current_subnet_last_scan_at?: string
  total_ips_scanned: number
  started_at?: string
  updated_at?: string
  last_completed_at?: string
  summary?: IPAMScanSummary | Record<string, any> | null
}

export interface IPAMScanStartResponse {
  session_id: string
  message: string
  status: IPAMScanStatus
  mode?: 'async' | 'sync'
  summary?: IPAMScanSummary
}

export const ipamApi = {
  // Get IP address detail
  async getIPAddress(ipId: number): Promise<IPAddressDetail> {
    const response = await apiClient.get(`/api/v1/ipam/ip-addresses/${ipId}`)
    return response.data
  },

  // Get IP scan history
  async getIPScanHistory(ipId: number): Promise<IPScanHistory[]> {
    const response = await apiClient.get(`/api/v1/ipam/ip-addresses/${ipId}/history`)
    return response.data
  },

  async getScanStatus(): Promise<IPAMScanStatus> {
    const response = await apiClient.get('/api/v1/ipam/scan-status', {
      skipDefaultErrorHandler: true
    } as any)
    return response.data
  },

  async startSubnetScan(subnetId: number, scanType: 'quick' | 'full' = 'full'): Promise<IPAMScanStartResponse> {
    try {
      const response = await apiClient.post('/api/v1/ipam/scan-stream', {
        subnet_id: subnetId,
        scan_type: scanType
      }, {
        skipDefaultErrorHandler: true
      } as any)
      return {
        ...response.data,
        mode: 'async'
      }
    } catch (error: any) {
      if (error.response?.status !== 404) {
        throw error
      }

      const response = await apiClient.post('/api/v1/ipam/scan', {
        subnet_id: subnetId,
        scan_type: scanType
      }, {
        skipDefaultErrorHandler: true
      } as any)

      return {
        session_id: '',
        message: '当前后端尚未重启到实时进度版本，已回退为同步扫描',
        status: {
          running: false,
          source: 'manual',
          scan_type: scanType,
          current_phase: 'completed',
          phase_label: '已完成',
          current_subnet_index: 1,
          total_subnets: 1,
          completed_subnets: 1,
          current_subnet_total_ips: response.data?.total_scanned || 0,
          current_subnet_completed_ips: response.data?.total_scanned || 0,
          current_subnet_pending_ips: 0,
          current_subnet_reachable_ips: response.data?.reachable || 0,
          current_subnet_unreachable_ips: response.data?.unreachable || 0,
          current_subnet_enrichment_total: response.data?.reachable || 0,
          current_subnet_enrichment_completed: response.data?.reachable || 0,
          total_ips_scanned: response.data?.total_scanned || 0,
          message: '同步扫描已完成',
          summary: response.data
        },
        mode: 'sync',
        summary: response.data
      }
    }
  },

  getScanEventsUrl(): string {
    return `${API_BASE_URL}/api/v1/ipam/scan-events`
  }
}
