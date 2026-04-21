import apiClient from './index'

export interface IPAddressDetail {
  id: number
  ip_address: string
  status: string
  is_reachable: boolean
  response_time?: number
  hostname?: string
  dns_name?: string
  system_name?: string
  machine_type?: string
  vendor?: string
  mac_address?: string
  os_type?: string
  os_name?: string
  os_version?: string
  switch_id?: number
  switch_name?: string
  switch_port?: string
  vlan_id?: number
  last_seen_at?: string
  last_boot_time?: string
  last_scan_at?: string
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
  }
}
