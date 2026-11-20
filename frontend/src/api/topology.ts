/**
 * Automatic Network Topology API (LLDP / CDP derived)
 */

import apiClient from './index'

export type TopologyLinkStatus = 'confirmed' | 'one_sided' | 'unresolved' | 'stale'

export interface TopologyLink {
  link_key: string
  source: string
  target: string
  status: TopologyLinkStatus
  confidence: number
  evidence: string | null
  is_lag: boolean
  conflict_reason: string | null
  a_switch_id: number | null
  a_if_index: number | null
  a_port_name: string | null
  a_sys_name: string | null
  a_mgmt_ip: string | null
  b_switch_id: number | null
  b_if_index: number | null
  b_port_name: string | null
  b_sys_name: string | null
  b_mgmt_ip: string | null
  first_seen: string | null
  last_seen: string | null
}

export interface TopologySwitchNode {
  id: string
  kind: 'switch'
  switch_id: number
  label: string
  sys_name: string | null
  mgmt_ip: string | null
  vendor: string | null
  enabled: boolean
  auto_collect_topology: boolean
  collection_status: string | null
  last_collection_at: string | null
  neighbors_count: number | null
  degree: number
}

export interface TopologyUnknownNode {
  id: string
  kind: 'unknown'
  node_key: string | null
  label: string
  sys_name: string | null
  mgmt_ip: string | null
  chassis_id: string | null
  vendor_hint: string | null
  device_class: string | null
  seen_count: number | null
  degree: number
}

export type TopologyNode = TopologySwitchNode | TopologyUnknownNode

export interface TopologyCoverage {
  switches_total: number
  switches_enabled: number
  auto_collect: number
  collected: number
  not_collected: number
  success: number
  partial: number
  unsupported: number
  failed: number
  links: Record<string, number>
  unknown_nodes: number
}

export interface TopologyGraphResult {
  nodes: TopologyNode[]
  links: TopologyLink[]
  coverage: TopologyCoverage
  truncated: boolean
}

export interface TopologyLinkPage {
  total: number
  page: number
  page_size: number
  items: TopologyLink[]
}

export interface TopologyNeighbor {
  id: number
  switch_id: number
  protocol: 'lldp' | 'cdp'
  local_if_index: number | null
  local_port_id: string | null
  local_port_desc: string | null
  remote_chassis_id: string | null
  remote_port_id: string | null
  remote_port_desc: string | null
  remote_sys_name: string | null
  remote_sys_desc: string | null
  remote_mgmt_addr: string | null
  capability: string | null
  last_seen: string | null
}

export interface TopologyInterface {
  switch_id: number
  if_index: number
  if_name: string | null
  if_descr: string | null
  if_alias: string | null
  if_type: number | null
  admin_status: string | null
  oper_status: string | null
  speed_mbps: number | null
  phys_address: string | null
  lag_key: string | null
  last_seen: string | null
}

export interface TopologyCollectResult {
  queued: number
  switches: number
  skipped?: number
  message?: string
}

export function getTopologyStatus() {
  return apiClient.get<TopologyCoverage>('/api/v1/topology/status')
}

export function getTopologyGraph(params: {
  focus_switch_id?: number
  depth?: number
  switch_status?: string
} = {}) {
  return apiClient.get<TopologyGraphResult>('/api/v1/topology/graph', { params })
}

export function getTopologyLinks(params: {
  status?: string
  q?: string
  page?: number
  page_size?: number
} = {}) {
  return apiClient.get<TopologyLinkPage>('/api/v1/topology/links', { params })
}

export function getTopologyNeighbors(params: { switch_id?: number; protocol?: 'lldp' | 'cdp'; limit?: number } = {}) {
  return apiClient.get<TopologyNeighbor[]>('/api/v1/topology/neighbors', { params })
}

export function getTopologyInterfaces(params: { switch_id?: number; limit?: number } = {}) {
  return apiClient.get<TopologyInterface[]>('/api/v1/topology/interfaces', { params })
}

export function getTopologyUnknownNodes() {
  return apiClient.get<TopologyUnknownNode[]>('/api/v1/topology/unknown-nodes')
}

export function collectTopology(switchIds?: number[]) {
  return apiClient.post<TopologyCollectResult>('/api/v1/topology/collect', {
    switch_ids: switchIds && switchIds.length ? switchIds : null
  })
}

export function deriveTopologyLinks() {
  return apiClient.post('/api/v1/topology/derive')
}

export const TOPOLOGY_LINK_STATUS_LABEL: Record<string, string> = {
  confirmed: '双向确认',
  one_sided: '单向（对端未纳管）',
  unresolved: '未解析',
  stale: '过期'
}
