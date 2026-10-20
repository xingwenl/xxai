// 宿主 API 封装：与内嵌 FastAPI 的 /api/desktop/* 契约对应

export interface Plugin {
  id: string
  name: string
  version: string
  description: string
  icon: string
  entry: string
  type: 'iframe' | 'react' | 'remote'
  permissions: string[]
  /** 插件声明的默认打开方式：壳内展开 / 系统浏览器 / 新的原生窗口 */
  openMode: 'inline' | 'browser' | 'window'
  url: string | null
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

/** 从公网 URL 安装远程壳插件；frameable 为空表示无法预判嵌入性。 */
export function installFromUrl(body: {
  url: string
  name?: string
  description?: string
  iconUrl?: string
}): Promise<{ plugin: Plugin; frameable: boolean | null }> {
  return request('/api/desktop/plugins/install-from-url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

/** 编辑 remote 插件元数据（名称 / 描述 / 图标 URL，URL 保持不变）。 */
export function updatePluginMetadata(
  id: string,
  body: { name?: string; description?: string; iconUrl?: string },
): Promise<{ plugin: Plugin }> {
  return request(`/api/desktop/plugins/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

/** 重新抓取 remote 插件元数据（名称 / 描述 / 图标）。 */
export function refreshMetadata(id: string): Promise<{ plugin: Plugin }> {
  return request(`/api/desktop/plugins/${encodeURIComponent(id)}/refresh-metadata`, {
    method: 'POST',
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

// ── 全局助手连接配置 ─────────────────────────────────────────────────────────

/** 宿主智能体配置；enabled=false 表示当前没有可用的智能体后端（含本地开发网关）。 */
export interface AgentConfig {
  enabled: boolean
  mode?: 'dev' | 'remote'
  /** WebSocket 地址，可能是相对路径（如 /api/v1/ws/agents/local） */
  endpoint?: string
  platformId?: string
  agentId?: string
  /** 本地开发网关的一次性 token；接入 AI Base 时应改为服务端换发的短期 token */
  token?: string
  displayName?: string
  version?: string
  reason?: string
}

/** 读取宿主当前可用的智能体连接参数；没有配置时返回 enabled=false。 */
export function getAgentConfig(): Promise<AgentConfig> {
  return request('/api/desktop/agent-config')
}

// ── 子应用本地数据（plugin-data） ────────────────────────────────────────────
// 由宿主落盘到 ~/.desktop-app/plugin-data/<pluginId>/<key>.json，
// 子应用不直接接触文件系统，只通过这组接口读写自己的键值。

function pluginDataPath(pluginId: string, key: string): string {
  return `/api/desktop/plugin-data/${encodeURIComponent(pluginId)}/${encodeURIComponent(key)}`
}

/** 键不存在时返回 null（与「值为 null」不可区分，子应用应避免存 null）。 */
export async function getPluginData(pluginId: string, key: string): Promise<unknown | null> {
  try {
    return await request<unknown>(pluginDataPath(pluginId, key))
  } catch (e) {
    if (e instanceof Error && e.message.includes('数据不存在')) return null
    throw e
  }
}

export function setPluginData(pluginId: string, key: string, value: unknown): Promise<{ ok: boolean }> {
  return request(pluginDataPath(pluginId, key), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    // undefined 不是合法 JSON，统一落成 null，避免发空 body 被宿主拒绝
    body: JSON.stringify(value === undefined ? null : value),
  })
}

export function deletePluginData(pluginId: string, key: string): Promise<null> {
  return request(pluginDataPath(pluginId, key), { method: 'DELETE' })
}

export function listPluginDataKeys(pluginId: string): Promise<{ keys: string[] }> {
  return request(`/api/desktop/plugin-data/${encodeURIComponent(pluginId)}`)
}
