import { getIdToken, refreshTokens, logout, getCurrentUser } from './cognito'

const API_URL = import.meta.env.VITE_API_URL as string

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  let token = await getIdToken()
  if (!token) {
    const ok = await refreshTokens()
    if (!ok) { logout(); throw new Error('Not authenticated') }
    token = await getIdToken()
  }
  const user = await getCurrentUser()

  const headers = new Headers(init.headers)
  headers.set('Authorization', `Bearer ${token}`)
  if (user) headers.set('X-User-Id', user.sub)
  if (!headers.has('Content-Type') && init.body) headers.set('Content-Type', 'application/json')

  const url = path.startsWith('http') ? path : `${API_URL.replace(/\/$/, '')}/${path.replace(/^\//, '')}`
  return fetch(url, { ...init, headers })
}
