import apiClient from './index'

export type ProbeMode = 'fast' | 'full'
export type ProbeStatus = 'running' | 'completed' | 'cancelled' | 'failed'

export interface SubnetProbeParseResult {
  subnets: string[]
  total_hosts: number
  invalid: string[]
}

export interface AliveHost {
  ip: string
  response_time_ms: number | null
}

export interface SubnetProbeEntry {
  subnet: string
  has_live: boolean
  alive_count: number
  alive_ips: AliveHost[]
  probed_hosts: number
  total_hosts: number
  truncated: boolean
  duration_ms: number
  error?: string | null
}

export interface SubnetProbeSummary {
  total_subnets: number
  checked_subnets: number
  alive_subnets: number
  dead_subnets: number
  alive_hosts: number
  pings_sent: number
}

export interface SubnetProbeStartResult {
  task_id: string
  status: ProbeStatus
  total_subnets: number
  total_hosts: number
  mode: ProbeMode
  concurrency: number
  timeout: number
}

export interface SubnetProbeStatusResult {
  task_id: string
  status: ProbeStatus
  mode: ProbeMode
  progress_percent: number
  summary: SubnetProbeSummary
  elapsed_seconds: number
  eta_seconds: number | null
  started_at?: string | null
  finished_at?: string | null
  message?: string | null
}

export interface SubnetProbeResult {
  task_id: string
  status: ProbeStatus
  mode: ProbeMode
  concurrency: number
  timeout: number
  started_at?: string | null
  finished_at?: string | null
  elapsed_seconds: number
  summary: SubnetProbeSummary
  results: SubnetProbeEntry[]
}

export interface SubnetProbeStartParams {
  subnets: string
  mode: ProbeMode
  concurrency?: number
  timeout?: number
  gateway_first?: boolean
}

const BASE = '/api/v1/subnet-probe'

// The backend reports input problems as detail={"message": "...", "invalid": [...]},
// which the default interceptor cannot render, so these calls format it themselves.
const silentConfig = { skipDefaultErrorHandler: true } as any

function toReadableError(error: any): Error {
  const detail = error?.response?.data?.detail
  if (detail && typeof detail === 'object' && detail.message) {
    const invalid: string[] = Array.isArray(detail.invalid) ? detail.invalid : []
    const extra = invalid.length
      ? `（无法识别：${invalid.slice(0, 5).join('、')}${invalid.length > 5 ? ' 等' : ''}）`
      : ''
    return new Error(`${detail.message}${extra}`)
  }
  if (typeof detail === 'string' && detail) {
    return new Error(detail)
  }
  return error instanceof Error ? error : new Error('请求失败')
}

export const subnetProbeApi = {
  async parse(subnets: string): Promise<SubnetProbeParseResult> {
    try {
      const { data } = await apiClient.post(`${BASE}/parse`, { subnets }, silentConfig)
      return data
    } catch (error) {
      throw toReadableError(error)
    }
  },

  async start(params: SubnetProbeStartParams): Promise<SubnetProbeStartResult> {
    try {
      const { data } = await apiClient.post(`${BASE}/start`, params, silentConfig)
      return data
    } catch (error) {
      throw toReadableError(error)
    }
  },

  async status(taskId: string): Promise<SubnetProbeStatusResult> {
    const { data } = await apiClient.get(`${BASE}/status/${taskId}`, silentConfig)
    return data
  },

  async result(taskId: string): Promise<SubnetProbeResult> {
    const { data } = await apiClient.get(`${BASE}/result/${taskId}`, silentConfig)
    return data
  },

  async cancel(taskId: string): Promise<SubnetProbeStatusResult> {
    try {
      const { data } = await apiClient.post(`${BASE}/cancel/${taskId}`, {}, silentConfig)
      return data
    } catch (error) {
      throw toReadableError(error)
    }
  },

  async running(): Promise<{ task_id: string | null }> {
    const { data } = await apiClient.get(`${BASE}/running`, silentConfig)
    return data
  }
}
