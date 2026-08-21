// 宿主 API 封装：与内嵌 FastAPI 的 /api/desktop/* 契约对应

export interface Plugin {
  id: string
  name: string
  version: string
  description: string
  icon: string
  entry: string
  type: 'iframe' | 'react'
  permissions: string[]
  builtin: boolean
  enabled: boolean
  installedAt: string | null
  error: string | null
  iconUrl: string | null
  entryUrl: string
}

export interface DesktopSettings {
  name: string
  version: string
  pluginsDir: string
  userDataDir: string
}

export interface BookmarkItem {
  id: string
  title: string
  url: string
  folderPath: string
}

export interface BookmarkGroup {
  folderPath: string
  count: number
  items: BookmarkItem[]
}

export interface BookmarkSummary {
  collectedAt: string
  total: number
  unique: number
  filtered: number
  groups: BookmarkGroup[]
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

/** 获取最近一次整理的书签快照；尚无快照时后端返回 404（调用方需区分处理）。 */
export async function getBookmarkSummary(): Promise<BookmarkSummary | null> {
  try {
    return await request('/api/desktop/bookmarks/summary')
  } catch (e) {
    if (e instanceof Error && e.message.includes('尚未整理')) return null
    throw e
  }
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
