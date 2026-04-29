/**
 * SNMP Configuration API Client
 */

import apiClient from './index';

export interface SNMPConfig {
  snmp_enabled: boolean;
  snmp_version: '2c' | '3';
  snmp_username?: string;
  snmp_auth_protocol?: 'MD5' | 'SHA' | 'SHA256' | 'SHA384' | 'SHA512';
  snmp_auth_password?: string;
  snmp_priv_protocol?: 'DES' | 'AES' | 'AES128' | 'AES192' | 'AES256';
  snmp_priv_password?: string;
  snmp_port?: number;
  snmp_community?: string;
}

export interface SNMPConfigResponse {
  switch_id: number;
  switch_name: string;
  switch_ip: string;
  snmp_enabled: boolean;
  snmp_version: string;
  snmp_username?: string;
  snmp_auth_protocol?: string;
  snmp_priv_protocol?: string;
  snmp_port: number;
  has_credentials: boolean;
}

export interface SNMPTestRequest {
  target_ip: string;
  snmp_version: '2c' | '3';
  snmp_username?: string;
  snmp_auth_protocol?: string;
  snmp_auth_password?: string;
  snmp_priv_protocol?: string;
  snmp_priv_password?: string;
  snmp_port?: number;
  snmp_community?: string;
}

export interface SNMPTestResponse {
  success: boolean;
  message: string;
  system_description?: string;
  target_ip?: string;
  snmp_version?: string;
  error_type?: string;
}

export interface SwitchSNMPStatus {
  id: number;
  name: string;
  ip_address: string;
  vendor: string;
  role: string;
  snmp_enabled: boolean;
  snmp_version: string;
  snmp_username?: string;
  has_credentials: boolean;
  enabled: boolean;
}

/**
 * Get SNMP configuration for a switch
 */
export async function getSNMPConfig(switchId: number): Promise<SNMPConfigResponse> {
  const response = await apiClient.get(`/api/v1/snmp/config/${switchId}`);
  return response.data;
}

/**
 * Update SNMP configuration for a switch
 */
export async function updateSNMPConfig(switchId: number, config: SNMPConfig): Promise<any> {
  const response = await apiClient.put(`/api/v1/snmp/config/${switchId}`, config);
  return response.data;
}

/**
 * Batch update SNMP configuration for multiple switches
 */
export async function batchUpdateSNMPConfig(switchIds: number[], config: SNMPConfig): Promise<any> {
  const response = await apiClient.post(`/api/v1/snmp/config/batch`, {
    switch_ids: switchIds,
    snmp_config: config
  });
  return response.data;
}

/**
 * Test SNMP connection
 */
export async function testSNMPConnection(testConfig: SNMPTestRequest): Promise<SNMPTestResponse> {
  const response = await apiClient.post(`/api/v1/snmp/test`, testConfig);
  return response.data;
}

/**
 * List all switches with SNMP configuration status
 */
export async function listSNMPConfiguredSwitches(): Promise<{ total: number; switches: SwitchSNMPStatus[] }> {
  const response = await apiClient.get(`/api/v1/snmp/switches/configured`);
  return response.data;
}

/**
 * Delete SNMP configuration from a switch
 */
export async function deleteSNMPConfig(switchId: number): Promise<any> {
  const response = await apiClient.delete(`/api/v1/snmp/config/${switchId}`);
  return response.data;
}
