import apiClient from './index'

export interface IPLookupSettings {
  cache_hours: number
  cache_hours_min: number
  cache_hours_max: number
}

export interface SettingResponse {
  key: string
  value: any
  data_type: string
  description?: string
  is_configurable: boolean
}

export interface AllSettingsResponse {
  settings: SettingResponse[]
  total: number
}

export const settingsApi = {
  // Get IP Lookup settings
  getIPLookupSettings: async (): Promise<IPLookupSettings> => {
    const response = await apiClient.get('/api/v1/settings/lookup')
    return response.data
  },

  // Update cache hours
  updateCacheHours: async (cacheHours: number): Promise<SettingResponse> => {
    const response = await apiClient.put('/api/v1/settings/lookup/cache-hours', {
      value: cacheHours
    })
    return response.data
  },

  // Get all configurable settings
  getAllSettings: async (): Promise<AllSettingsResponse> => {
    const response = await apiClient.get('/api/v1/settings/all')
    return response.data
  }
}
