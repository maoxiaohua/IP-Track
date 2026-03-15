/**
 * Command Templates API
 */

import apiClient from './index'

export interface CommandTemplate {
  id?: number
  vendor: string
  model_pattern: string
  name_pattern?: string
  device_type: string
  arp_command?: string
  arp_parser_type?: string
  arp_enabled: boolean
  mac_command?: string
  mac_parser_type?: string
  mac_enabled: boolean
  priority: number
  description?: string
  is_builtin?: boolean
  enabled: boolean
  created_at?: string
  updated_at?: string
}

export interface TestConnectionRequest {
  switch_ip: string
  switch_username: string
  switch_password: string
  template_id: number
  test_type: 'arp' | 'mac'
}

export interface TestConnectionResponse {
  success: boolean
  message: string
  entries_count: number
  sample_output: string
  error: string
}

export interface ParserInfo {
  type: string
  name: string
  description: string
}

export interface AvailableParsers {
  arp: ParserInfo[]
  mac: ParserInfo[]
}

/**
 * Get available parsers for ARP and MAC collection
 */
export function getAvailableParsers() {
  return apiClient.get<AvailableParsers>('/api/v1/command-templates/parsers')
}

/**
 * Get all command templates
 */
export function getCommandTemplates(enabledOnly = false) {
  return apiClient.get('/api/v1/command-templates', {
    params: { enabled_only: enabledOnly }
  })
}

/**
 * Get a single command template
 */
export function getCommandTemplate(id: number) {
  return apiClient.get(`/api/v1/command-templates/${id}`)
}

/**
 * Create a new command template
 */
export function createCommandTemplate(data: CommandTemplate) {
  return apiClient.post('/api/v1/command-templates', data)
}

/**
 * Update a command template
 */
export function updateCommandTemplate(id: number, data: Partial<CommandTemplate>) {
  return apiClient.put(`/api/v1/command-templates/${id}`, data)
}

/**
 * Delete a command template
 */
export function deleteCommandTemplate(id: number) {
  return apiClient.delete(`/api/v1/command-templates/${id}`)
}

/**
 * Test a command template
 */
export function testCommandTemplate(data: TestConnectionRequest): Promise<TestConnectionResponse> {
  return apiClient.post('/api/v1/command-templates/test', data)
}
