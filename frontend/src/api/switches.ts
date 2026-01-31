import apiClient from './index'

export interface Switch {
  id: number
  name: string
  ip_address: string
  vendor: 'cisco' | 'dell' | 'alcatel'
  model?: string
  role: 'core' | 'aggregation' | 'access'
  priority: number
  ssh_port: number
  username: string
  connection_timeout: number
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface SwitchCreate {
  name: string
  ip_address: string
  vendor: 'cisco' | 'dell' | 'alcatel'
  model?: string
  role?: 'core' | 'aggregation' | 'access'
  priority?: number
  ssh_port?: number
  username: string
  password: string
  enable_password?: string
  connection_timeout?: number
  enabled?: boolean
}

export interface SwitchUpdate {
  name?: string
  ip_address?: string
  vendor?: 'cisco' | 'dell' | 'alcatel'
  model?: string
  ssh_port?: number
  username?: string
  password?: string
  enable_password?: string
  connection_timeout?: number
  enabled?: boolean
}

export interface SwitchTestResponse {
  success: boolean
  message: string
  details?: any
}

export const switchesApi = {
  // Get all switches
  list: async (): Promise<Switch[]> => {
    const response = await apiClient.get('/api/v1/switches')
    return response.data
  },

  // Get a specific switch
  get: async (id: number): Promise<Switch> => {
    const response = await apiClient.get(`/api/v1/switches/${id}`)
    return response.data
  },

  // Create a new switch
  create: async (data: SwitchCreate): Promise<Switch> => {
    const response = await apiClient.post('/api/v1/switches', data)
    return response.data
  },

  // Update a switch
  update: async (id: number, data: SwitchUpdate): Promise<Switch> => {
    const response = await apiClient.put(`/api/v1/switches/${id}`, data)
    return response.data
  },

  // Delete a switch
  delete: async (id: number): Promise<void> => {
    await apiClient.delete(`/api/v1/switches/${id}`)
  },

  // Test switch connection
  test: async (id: number): Promise<SwitchTestResponse> => {
    const response = await apiClient.post(`/api/v1/switches/${id}/test`)
    return response.data
  }
}
