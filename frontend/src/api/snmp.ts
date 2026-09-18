/**
 * SNMP Configuration API Client
 */

import apiClient from './index';

export interface SNMPConfig {
  snmp_enabled: boolean;
  snmp_version: '2c' | '3';
  snmp_username?: string;
  // 协议名放宽到带连字符的写法：模板表里存的就是 SHA-256 / AES-192 这种形式。
  // 下拉选项也按这个来，两边用同一套字符串，避免选了 SHA-256 却被当成 SHA 发出去。
  snmp_auth_protocol?: string;
  snmp_auth_password?: string;
  snmp_priv_protocol?: string;
  snmp_priv_password?: string;
  snmp_port?: number;
  snmp_community?: string;
  // 引用模板：非空时上面的逐台凭据字段后端一律忽略，凭据整体以模板为准；
  // 显式传 null 表示解绑。（可选字段，不传 = 不改动现有绑定）
  snmp_profile_id?: number | null;
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
  // 凭据来源模板；非空表示上面那些值是模板上的生效值
  snmp_profile_id?: number | null;
  snmp_profile_name?: string | null;
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
  raw_error?: string;
  // 这份凭据是模板给的还是交换机自带的。改了模板口令却毫无变化时，
  // 靠它能立刻分清是「本来就用模板」还是「模板没生效」。
  credential_source?: string;
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
  snmp_profile_id?: number | null;
  snmp_profile_name?: string | null;
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
 * Test a switch using the credentials already saved in the database.
 *
 * 引用模板的交换机在界面上拿不到明文口令，只能用这个接口测 —— 凭据由服务端
 * 按统一解析路径取出，和后台采集用的是同一份。
 */
export async function testSavedSNMPConfig(switchId: number): Promise<SNMPTestResponse> {
  const response = await apiClient.post(`/api/v1/snmp/test/${switchId}`);
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
