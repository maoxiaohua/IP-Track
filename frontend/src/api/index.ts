import axios from 'axios'
import { ElMessage } from 'element-plus'

// Dynamically determine API base URL
const getApiBaseUrl = () => {
  // In development with Vite proxy, use empty string for relative paths
  // Vite will proxy /api/* requests to the backend
  if (import.meta.env.DEV) {
    console.log('Using Vite proxy for API requests')
    return ''
  }

  // Priority 1: Use environment variable if set (for production)
  const envUrl = import.meta.env.VITE_API_BASE_URL
  if (envUrl) {
    console.log('Using env API URL:', envUrl)
    return envUrl
  }

  // Priority 2: Use current hostname with backend port
  const protocol = window.location.protocol
  const hostname = window.location.hostname

  // If accessing via localhost/127.0.0.1, check if we should use server IP instead
  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    // Try to use the same host but warn that it might not work
    console.warn('Accessing via localhost - API calls may fail if backend is not on localhost')
  }

  // Microservice deployments should use either the current origin behind a
  // reverse proxy or an explicit VITE_API_BASE_URL. Do not fall back to the
  // retired monolithic backend port.
  const url = `${protocol}//${hostname}${window.location.port ? `:${window.location.port}` : ''}`
  console.log('Computed API URL from current origin:', url)
  return url
}

const apiClient = axios.create({
  baseURL: getApiBaseUrl(),
  timeout: 320000,  // 320s timeout for Alcatel optical module collection (52 ports query)
  headers: {
    'Content-Type': 'application/json'
  }
})

// Export API base URL for SSE connections
export const API_BASE_URL = getApiBaseUrl()

// Log the API base URL for debugging
console.log('API Base URL initialized:', API_BASE_URL)

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
    if ((error.config as any)?.skipDefaultErrorHandler) {
      return Promise.reject(error)
    }

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
