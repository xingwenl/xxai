// 宿主 API 封装：与内嵌 FastAPI 的 /api/desktop/* 契约对应

/** manifest.settings[] 声明的一项配置：宿主据此渲染表单，并在保存时校验取值。 */
export interface PluginSetting {
  key: string
  label: string
  type: 'text' | 'number' | 'boolean' | 'select'
  default: unknown
  description: string
  options: { label: string; value: string }[]
  min: number | null
  max: number | null
}

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
  /** manifest 声明的配置项；空数组表示不需要宿主渲染配置表单 */
  settings: PluginSetting[]
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
  /** 插件宿主配置目录（~/.desktop-app/plugin-config） */
  pluginConfigDir: string
  /** 插件生命周期日志文件（~/.desktop-app/plugin.log） */
  pluginLogFile: string
  /** 开发热重载是否开启（宿主以 DESKTOP_DEV_RELOAD=1 启动时为 true） */
  devReload: boolean
  /** 插件市场索引地址；市场关闭时为空串 */
  marketUrl: string
  /** 宿主更新清单地址；更新检查关闭时为空串 */
  appUpdateUrl: string
  /** 宿主更新检查是否启用（DESKTOP_APP_UPDATE=0 时为 false） */
  appUpdateEnabled: boolean
}

/** 插件树指纹：开发热重载靠比较 revision 判断「插件目录有没有变」。 */
export interface PluginRevision {
  enabled: boolean
  /** 整棵插件树的摘要；enabled=false 时为空串 */
  revision: string
  /** 插件 id → 该插件目录的指纹，用于定位哪个插件变了 */
  plugins: Record<string, string>
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

/** 把后端错误体 {"detail": 中文} 转成中文 Error；所有 REST 客户端的统一错误出口。 */
async function toApiError(resp: Response): Promise<Error> {
  const body = await resp.json().catch(() => null)
  return new Error((body && (body.detail || body.message)) || resp.statusText)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, init)
  if (!resp.ok) throw await toApiError(resp)
  return resp.status === 204 ? (null as T) : resp.json()
}

export function getPlugins(): Promise<{ items: Plugin[] }> {
  return request('/api/desktop/plugins')
}

export function getDesktopSettings(): Promise<DesktopSettings> {
  return request('/api/desktop/settings')
}

/** 取插件树指纹（开发热重载）；未开启时返回 enabled=false，不产生磁盘遍历。 */
export function getPluginRevision(): Promise<PluginRevision> {
  return request('/api/desktop/plugin-revision')
}

/** 市场索引里的一条插件记录（与 apps/desktop/market/index.json 的字段一一对应）。 */
export interface MarketEntry {
  id: string
  name: string
  version: string
  description: string
  /** 插件包下载地址（https，本机开发可为回环 http / file） */
  download: string
  /** 插件包的 sha256（64 位十六进制），宿主下载后逐字节校验 */
  sha256: string
  /** 插件包字节数；索引里可选，出现时宿主会校大小 */
  size: number | null
  permissions: string[]
  /** 下载镜像：主下载地址不可用时宿主按顺序回退（例如 Gitee raw） */
  mirrors: string[]
  /** 本机已安装版本；未安装为空串 */
  installedVersion: string
  /** 索引版本是否高于本机版本（版本比较只在宿主侧做） */
  hasUpdate: boolean
}

/** 市场列表：索引条目 + 本机已安装版本（id → version）。 */
export interface PluginMarket {
  enabled: boolean
  source: string
  plugins: MarketEntry[]
  installed: Record<string, string>
}

/** 拉取市场索引；refresh=true 跳过宿主侧 5 分钟缓存。 */
export function getPluginMarket(refresh = false): Promise<PluginMarket> {
  return request(`/api/desktop/plugin-market${refresh ? '?refresh=1' : ''}`)
}

/** 按市场 id 安装插件：宿主负责下载、校 sha256 与包内 manifest，再交给安装流程。 */
export function installMarketPlugin(id: string): Promise<{ plugin: Plugin }> {
  return request('/api/desktop/plugin-market/install', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  })
}

/** 把已安装插件升级到市场版本；宿主会备份旧目录并在失败时回滚。 */
export function updateMarketPlugin(id: string): Promise<{ plugin: Plugin }> {
  return request('/api/desktop/plugin-market/update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  })
}

/** 当前平台的发布资产（对应 releases/latest.json 的 platforms[platform]）。 */
export interface AppUpdateAsset {
  platform: string
  name: string
  url: string
  sha256: string
  size: number
  mirrors: string[]
}

/** 宿主更新状态：检查失败时 error 有中文原因，不要把失败当成「已是最新」。 */
export interface AppUpdateInfo {
  enabled: boolean
  current: string
  latest: string
  hasUpdate: boolean
  platform: string
  publishedAt: string
  notes: string
  releaseUrl: string
  asset: AppUpdateAsset | null
  /** 已下载到本机的完整路径；未下载为空串 */
  downloadedPath: string
  source: string
  error: string
}

/** 检查宿主更新；refresh=true 跳过宿主侧 10 分钟清单缓存。 */
export function getAppUpdate(refresh = false): Promise<AppUpdateInfo> {
  return request(`/api/desktop/app-update${refresh ? '?refresh=1' : ''}`)
}

/** 下载并校验当前平台更新包到本机更新目录（只落盘，不替换宿主）。 */
export function downloadAppUpdate(): Promise<{
  version: string
  path: string
  size: number
  sha256: string
}> {
  return request('/api/desktop/app-update/download', { method: 'POST' })
}

/**
 * 自动安装已下载的更新包：宿主会起一个脱离进程的安装脚本替换 .app 并重启。
 * 接口返回后宿主会在 2 秒内退出，调用方不要依赖它返回后再更新界面。
 */
export function installAppUpdate(): Promise<{
  version: string
  bundle: string
  script: string
  log: string
}> {
  return request('/api/desktop/app-update/install', { method: 'POST' })
}

/** 在系统文件管理器里打开更新目录（自动安装不可用时手动兜底）。 */
export function revealAppUpdates(): Promise<{ path: string }> {
  return request('/api/desktop/app-update/reveal', { method: 'POST' })
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

/** 宿主智能体配置；enabled=false 表示当前没有可用的智能体后端（含 AI Base 与本地开发网关）。 */
export interface AgentConfig {
  enabled: boolean
  /** remote = 真实 AI Base（宿主换 token）；dev = 本地规则式网关 */
  mode?: 'dev' | 'remote'
  /** WebSocket 地址，可能是相对路径（如 /api/v1/ws/agents/local） */
  endpoint?: string
  platformId?: string | number
  /** 本地网关是 "local"，AI Base 是数字 ID */
  agentId?: string | number
  /** 仅本地开发网关下发的一次性 token；remote 模式由 agent-token 接口现换 */
  token?: string
  displayName?: string
  version?: string
  reason?: string
  /** 以下字段仅 remote 模式返回（不含 secret） */
  baseUrl?: string
  clientId?: string
  hostToolNames?: string[]
  externalUserId?: string
  hasSecret?: boolean
}

/** remote 模式下由宿主换发的短期 token 与连接参数。 */
export interface AgentTokenResult {
  token: string
  expiresIn: number
  /** 形如 ws://127.0.0.1:8000/api/v1/ws/agents/1 */
  endpoint: string
  platformId: string
  agentId: number
  displayName?: string
  mode: 'remote'
}

export interface AgentConfigInput {
  baseUrl: string
  clientId: string
  /** 留空表示沿用宿主已保存的 secret */
  clientSecret?: string
  agentId: number
  hostToolNames?: string[]
}

/** 读取宿主当前可用的智能体连接参数；没有配置时返回 enabled=false。 */
export function getAgentConfig(): Promise<AgentConfig> {
  return request('/api/desktop/agent-config')
}

/** 保存 AI Base 连接配置；secret 只落宿主进程，不会返回给渲染层。 */
export function saveAgentConfig(input: AgentConfigInput): Promise<{ ok: boolean; config: AgentConfig }> {
  return request('/api/desktop/agent-config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export function clearAgentConfig(): Promise<{ ok: boolean; removed: boolean }> {
  return request('/api/desktop/agent-config', { method: 'DELETE' })
}

/** 用宿主保存的 Client 凭证换短期 token；origin 必须是当前页面真实来源。 */
export function issueAgentToken(origin: string): Promise<AgentTokenResult> {
  return request('/api/desktop/agent-token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ origin }),
  })
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

// ── 插件资产（plugin-assets） ────────────────────────────────────────────────
// 二进制文件由宿主落盘到 ~/.desktop-app/plugin-assets/<pluginId>/，与 plugin-data
// （JSON 键值、单值 256 KiB）分家；key 由服务端按内容 sha256 生成，客户端不参与命名，
// 因此同图重复上传天然去重，key 也可以放心长缓存。

/** 一个插件资产（图片等位图）；key 由宿主按内容生成，同图重复上传得到同一个 key。 */
export interface PluginAsset {
  key: string
  /** 站内绝对路径 /api/desktop/plugin-assets/<pluginId>/<key>，可直接放进 <img src> */
  url: string
  bytes: number
  mime: string
  createdAt: string
}

/** 该插件的资产用量与配额；上传前可先看剩余额度，避免撞 413。 */
export interface PluginAssetUsage {
  bytes: number
  count: number
  limitBytes: number
  limitCount: number
  limitFileBytes: number
}

function pluginAssetsPath(pluginId: string): string {
  return `/api/desktop/plugin-assets/${encodeURIComponent(pluginId)}`
}

/** 拼资产站内路径；纯函数，不校验资产是否存在（用于正文引用与 <img src>）。 */
export function pluginAssetUrl(pluginId: string, key: string): string {
  return `${pluginAssetsPath(pluginId)}/${encodeURIComponent(key)}`
}

/**
 * 列出插件已有资产与当前用量。
 *
 * 与「读单个资产文件」不同：列表、上传、删除都要求插件已启用且声明了 assets 权限（否则宿主 403）；
 * 只有 GET 单文件那一条对「插件已知」放开，好让停用插件的历史笔记图片不 404。
 */
export function listPluginAssets(
  pluginId: string,
): Promise<{ assets: PluginAsset[]; usage: PluginAssetUsage }> {
  return request(pluginAssetsPath(pluginId))
}

/**
 * 上传原始字节（不是 JSON，也不做 base64）：Content-Type 必须是 png/jpeg/webp/gif，
 * 否则宿主返回 415；超出单文件或插件配额返回 413，错因在中文 detail 里。
 */
export function uploadPluginAsset(
  pluginId: string,
  data: Blob | ArrayBuffer | Uint8Array,
  mime?: string,
): Promise<{ asset: PluginAsset; usage: PluginAssetUsage; created: boolean }> {
  return request(pluginAssetsPath(pluginId), {
    method: 'POST',
    headers: { 'Content-Type': resolveAssetMime(data, mime) },
    body: data as BodyInit,
  })
}

/** 删除资产（幂等，204）：只删文件，不校验是否还有正文引用它。 */
export function deletePluginAsset(pluginId: string, key: string): Promise<null> {
  return request(pluginAssetUrl(pluginId, key), { method: 'DELETE' })
}

/**
 * 决定上传用的 Content-Type：显式 mime > Blob 自带的 type > image/png。
 * 用鸭子类型而不是 instanceof Blob —— 子应用 iframe 与宿主不是同一个 realm，
 * 跨 realm 的 Blob 过不了宿主侧的原型判断（其 type 却是真实可读的）。
 */
function resolveAssetMime(data: Blob | ArrayBuffer | Uint8Array, mime?: string): string {
  const blobType = typeof (data as Blob).type === 'string' ? (data as Blob).type : ''
  return mime || blobType || 'image/png'
}

// ── 插件宿主配置（manifest.settings[]） ───────────────────────────────────────
// 配置由宿主落盘到 ~/.desktop-app/plugin-config/<pluginId>.json，
// 子应用只通过 SDK 读取（宿主负责校验与表单渲染）。

/** 读取插件配置：manifest 默认值与已保存值合并后的完整取值。 */
export function getPluginConfig(pluginId: string): Promise<{ values: Record<string, unknown> }> {
  return request(`/api/desktop/plugins/${encodeURIComponent(pluginId)}/config`)
}

/** 保存插件配置；值非法时宿主返回 400 并在 detail 里给出中文错因。 */
export function savePluginConfig(
  pluginId: string,
  values: Record<string, unknown>,
): Promise<{ values: Record<string, unknown> }> {
  return request(`/api/desktop/plugins/${encodeURIComponent(pluginId)}/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values }),
  })
}

/** 上报插件生命周期事件（iframe 加载 / SDK 注入 / 方法注册等）到宿主日志。 */
export function logPluginEvent(
  pluginId: string,
  event: string,
  detail?: string,
): Promise<{ ok: boolean }> {
  return request('/api/desktop/plugin-log', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pluginId, event, detail }),
  })
}
