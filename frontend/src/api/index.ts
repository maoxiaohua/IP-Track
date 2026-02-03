import axios from 'axios'
import { ElMessage } from 'element-plus'

// Dynamically determine API base URL
const getApiBaseUrl = () => {
  // If environment variable is set and not localhost, use it
  const envUrl = import.meta.env.VITE_API_BASE_URL
  if (envUrl && !envUrl.includes('localhost')) {
    return envUrl
  }

  // Otherwise, use current hostname with backend port
  const protocol = window.location.protocol
  const hostname = window.location.hostname
  const port = '8100'  // Backend port
  return `${protocol}//${hostname}:${port}`
}

const apiClient = axios.create({
  baseURL: getApiBaseUrl(),
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// Request interceptor
apiClient.interceptors.request.use(
  (config) => {
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor
apiClient.interceptors.response.use(
  (response) => {
    return response
  },
  (error) => {
    if (error.response) {
      const message = error.response.data?.detail || 'An error occurred'
      ElMessage.error(message)
    } else if (error.request) {
      ElMessage.error('Network error. Please check your connection.')
    } else {
      ElMessage.error('An unexpected error occurred')
    }
    return Promise.reject(error)
  }
)

export default apiClient
