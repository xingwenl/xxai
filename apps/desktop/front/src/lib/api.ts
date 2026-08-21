// 宿主 API 封装：与内嵌 FastAPI 的 /api/desktop/* 契约对应

export interface Plugin {
  id: string
  name: string
  version: string
  description: string
  icon: string
  entry: string
  permissions: string[]
  builtin: boolean
  enabled: boolean
  installedAt: string | null
  error: string | null
  iconUrl: string | null
  entryUrl: string
}

export interface DesktopSettings {
  version: string
  pluginsDir: string
  userDataDir: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, init)
  if (!resp.ok) {
    const body = await resp.json().catch(() => null)
    throw new Error((body && (body.detail || body.message)) || resp.statusText)
  }
  return resp.status === 204 ? (null as T) : resp.json()
}

export function getPlugins(): Promise<{ items: Plugin[] }> {
  return request('/api/desktop/plugins')
}

export function getDesktopSettings(): Promise<DesktopSettings> {
  return request('/api/desktop/settings')
}

export function setPluginEnabled(id: string, enabled: boolean): Promise<{ plugin: Plugin }> {
  return request(`/api/desktop/plugins/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  })
}

export function uninstallPlugin(id: string): Promise<null> {
  return request(`/api/desktop/plugins/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export function installPlugin(file: File): Promise<{ plugin: Plugin }> {
  return request('/api/desktop/plugins/install', {
    method: 'POST',
    headers: { 'Content-Type': 'application/zip' },
    body: file,
  })
}

/** HTTP 代理：插件 SDK 与宿主共享，经 /api/desktop/proxy 绕过 CORS。 */
export async function proxyFetch(method: 'GET' | 'POST', url: string, body?: unknown): Promise<unknown> {
  const data = await request<unknown>('/api/desktop/proxy', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      method,
      url,
      headers: {},
      body: body === undefined ? null : JSON.stringify(body),
    }),
  })
  if (typeof data === 'string') {
    try {
      return JSON.parse(data)
    } catch {
      return data
    }
  }
  return data
}
