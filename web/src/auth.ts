/**
 * 认证状态与 token 注入层（阶段1）。
 *
 * - access token（30min）+ refresh token（30天）存 localStorage；
 * - authFetch：所有 API 请求的统一出口——自动带 Bearer，遇 401 用 refresh 换新 token 后重放原请求（至多一次）；
 * - 并发 401 只触发一次刷新：后续请求等待同一个刷新 Promise 复用结果；
 * - 刷新失败（refresh 也过期/被吊销）→ 清空本地会话并广播 auth:expired 事件，
 *   App.tsx 监听后卸载工作台、回到登录页。
 */

const ACCESS_TOKEN_KEY = 'final-congee-access-token'
const REFRESH_TOKEN_KEY = 'final-congee-refresh-token'
const USER_KEY = 'final-congee-current-user'

export type AuthUser = {
  id: string
  email: string
  displayName: string
  role: string
  avatarUrl: string
}

export const AUTH_EXPIRED_EVENT = 'final-congee-auth-expired'

function readStored(key: string): string {
  try {
    return window.localStorage.getItem(key) ?? ''
  } catch {
    return ''
  }
}

function writeStored(key: string, value: string): void {
  try {
    if (value) window.localStorage.setItem(key, value)
    else window.localStorage.removeItem(key)
  } catch {
    // 存储不可用时不打断界面
  }
}

export function getAccessToken(): string {
  return readStored(ACCESS_TOKEN_KEY)
}

export function getRefreshTokenValue(): string {
  return readStored(REFRESH_TOKEN_KEY)
}

export function getStoredUser(): AuthUser | null {
  const raw = readStored(USER_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as AuthUser
    if (!parsed.id || !parsed.email) return null
    return { ...parsed, displayName: parsed.displayName || parsed.email, avatarUrl: parsed.avatarUrl || '' }
  } catch {
    return null
  }
}

export function saveSession(payload: {
  access_token: string
  refresh_token: string
  user: { id: string; email: string; display_name: string; role: string }
}): AuthUser {
  writeStored(ACCESS_TOKEN_KEY, payload.access_token)
  writeStored(REFRESH_TOKEN_KEY, payload.refresh_token)
  const user: AuthUser = {
    id: payload.user.id,
    email: payload.user.email,
    displayName: payload.user.display_name || payload.user.email,
    role: payload.user.role || 'user',
    avatarUrl: '',
  }
  writeStored(USER_KEY, JSON.stringify(user))
  return user
}

export function clearSession(): void {
  writeStored(ACCESS_TOKEN_KEY, '')
  writeStored(REFRESH_TOKEN_KEY, '')
  writeStored(USER_KEY, '')
}

export function updateStoredUser(patch: Partial<AuthUser>): AuthUser | null {
  const current = getStoredUser()
  if (!current) return null
  const next = { ...current, ...patch }
  writeStored(USER_KEY, JSON.stringify(next))
  return next
}

/** 已登录判定：有 refresh token 即视为会话存在（access 可刷新）。 */
export function hasSession(): boolean {
  return Boolean(readStored(REFRESH_TOKEN_KEY))
}

function notifyAuthExpired(): void {
  window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT))
}

/* ------------------------------------------------------------------ */
/* 登录 / 注册 / 刷新：唯一不走 authFetch 的三个请求（避免递归）        */

async function authRequest<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const response = await fetch(`/api/auth/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify(body),
  })
  const parsed = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(typeof parsed.detail === 'string' ? parsed.detail : '认证请求失败')
  }
  return parsed as T
}

type TokenPairPayload = {
  access_token: string
  refresh_token: string
  token_type: string
  user: { id: string; email: string; display_name: string; role: string }
}

export async function loginWithPassword(email: string, password: string): Promise<AuthUser> {
  const payload = await authRequest<TokenPairPayload>('login', { email, password })
  return saveSession(payload)
}

export async function registerAccount(
  email: string,
  password: string,
  displayName: string,
): Promise<AuthUser> {
  const payload = await authRequest<TokenPairPayload>('register', {
    email,
    password,
    display_name: displayName,
  })
  return saveSession(payload)
}

export async function logout(): Promise<void> {
  const refreshToken = getRefreshTokenValue()
  const accessToken = getAccessToken()
  clearSession()
  // 尽力通知服务端吊销；失败不影响本地登出
  if (accessToken) {
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json; charset=utf-8',
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
      })
    } catch {
      // 忽略：本地会话已清
    }
  }
}

/* ------------------------------------------------------------------ */
/* 刷新队列：并发 401 时只发一次 /api/auth/refresh                      */

let refreshInFlight: Promise<boolean> | null = null

async function refreshTokens(): Promise<boolean> {
  const refreshToken = getRefreshTokenValue()
  if (!refreshToken) return false
  try {
    const payload = await authRequest<TokenPairPayload>('refresh', {
      refresh_token: refreshToken,
    })
    saveSession(payload)
    return true
  } catch {
    clearSession()
    notifyAuthExpired()
    return false
  }
}

function refreshTokensQueued(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = refreshTokens().finally(() => {
      refreshInFlight = null
    })
  }
  return refreshInFlight
}

/* ------------------------------------------------------------------ */
/* authFetch：带 token 的请求 + 401 刷新重放                            */

export async function authFetch(path: string, init?: RequestInit): Promise<Response> {
  const fullPath = /^(?:https?:)?\/\//.test(path) || path.startsWith('/api') ? path : `/api${path}`
  const withAuth = async (): Promise<Response> => {
    const token = getAccessToken()
    const headers = new Headers(init?.headers)
    if (token) headers.set('Authorization', `Bearer ${token}`)
    return fetch(fullPath, { ...init, headers })
  }

  let response = await withAuth()
  if (response.status !== 401) return response

  // 可能是 access 过期：刷新后重放一次
  const refreshed = await refreshTokensQueued()
  if (!refreshed) return response
  response = await withAuth()
  if (response.status === 401) {
    // 新 token 仍 401（权限问题或账号异常）：按过期处理
    clearSession()
    notifyAuthExpired()
  }
  return response
}
