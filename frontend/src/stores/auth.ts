import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { apiClient } from '@/api/client'

export type PortalRole = 'personal' | 'admin' | 'enterprise'
export interface AuthUser { id: string; username: string; displayName: string; role: PortalRole }
export interface AuthSession { accessToken: string; expiresAt: number; user: AuthUser }

export const AUTH_STORAGE_KEY = 'ci_auth_session_v1'
export const DEMO_ACCESS_TOKEN = 'ci-local-product-preview'

export function readAuthSession(): AuthSession | null {
  try {
    const parsed = JSON.parse(localStorage.getItem(AUTH_STORAGE_KEY) || 'null') as AuthSession | null
    if (!parsed?.accessToken || !parsed.user || parsed.expiresAt <= Math.floor(Date.now() / 1000)) {
      localStorage.removeItem(AUTH_STORAGE_KEY)
      return null
    }
    return parsed
  } catch {
    localStorage.removeItem(AUTH_STORAGE_KEY)
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  const session = ref<AuthSession | null>(readAuthSession())
  const user = computed(() => session.value?.user || null)
  const isAuthenticated = computed(() => Boolean(session.value && session.value.expiresAt > Math.floor(Date.now() / 1000)))

  async function login(username: string, password: string, portal: PortalRole) {
    const response = await apiClient.post('/auth/login', { username, password, portal })
    session.value = response.data.data as AuthSession
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session.value))
    return session.value
  }

  async function register(username: string, password: string, displayName: string) {
    const response = await apiClient.post('/auth/register', { username, password, displayName })
    session.value = response.data.data as AuthSession
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session.value))
    return session.value
  }

  function enterPreview(displayName = '产品体验用户') {
    session.value = {
      accessToken: DEMO_ACCESS_TOKEN,
      expiresAt: Math.floor(Date.now() / 1000) + 12 * 60 * 60,
      user: { id: 'preview-user', username: 'preview', displayName, role: 'personal' },
    }
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session.value))
    return session.value
  }

  function logout() {
    session.value = null
    localStorage.removeItem(AUTH_STORAGE_KEY)
  }

  return { session, user, isAuthenticated, login, register, enterPreview, logout }
})
