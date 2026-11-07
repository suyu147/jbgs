import axios from 'axios'

const AUTH_STORAGE_KEY = 'ci_auth_session_v1'
type StoredSession = { accessToken: string }

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
})

export function apiUrl(endpoint: string): string {
  return `${apiClient.defaults.baseURL!.replace(/\/$/, '')}/${endpoint.replace(/^\//, '')}`
}

apiClient.interceptors.request.use(config => {
  try {
    const session = JSON.parse(localStorage.getItem(AUTH_STORAGE_KEY) || 'null') as StoredSession | null
    if (session?.accessToken) config.headers.Authorization = `Bearer ${session.accessToken}`
  } catch { /* Invalid local state is handled by the response interceptor. */ }
  return config
})

apiClient.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401 && !String(error.config?.url || '').includes('/auth/login')) {
      localStorage.removeItem(AUTH_STORAGE_KEY)
      if (window.location.pathname !== '/login') window.location.assign('/login')
    }
    return Promise.reject(new Error(error.response?.data?.detail || error.response?.data?.message || '本地服务不可用，请检查 8010 端口'))
  },
)
