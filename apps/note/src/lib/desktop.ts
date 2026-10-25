/**
 * 桌面宿主 SDK 适配层。
 *
 * 宿主动态注入 window.desktop（可能晚于 iframe load），注入后会在 window 上派发
 * `desktop-ready` 事件。本模块只做「类型声明 + 安全访问」：任何能力缺失都不应让页面崩，
 * 而是回退到浏览器本地模式——笔记应用在纯浏览器里也必须能独立使用。
 */

/** 宿主 storage 能力：值会 JSON 序列化后落到宿主磁盘。 */
export interface DesktopStorage {
  get(key: string): Promise<unknown | null>
  set(key: string, value: unknown): Promise<void>
  delete?(key: string): Promise<void>
  keys?(): Promise<string[]>
}

/** 工具定义；sideEffect 供宿主做权限/确认策略。 */
export interface DesktopToolDef {
  name: string
  description: string
  inputSchema: Record<string, unknown>
  sideEffect?: 'none' | 'financial' | 'write'
}

/** 工具执行体：入参由宿主透传，这里按 unknown 收敛后自行校验。 */
export type DesktopToolHandler = (args: unknown) => unknown | Promise<unknown>

/** 宿主 tools 能力：把子应用的方法暴露给全局助手。 */
export interface DesktopTools {
  register(defs: DesktopToolDef[], handlers: Record<string, DesktopToolHandler>): Promise<void>
  unregister?(names: string[]): Promise<void>
}

/**
 * 插件资产：二进制（图片）独立于 plugin-data 落盘，key 由服务端按内容哈希生成。
 * 只有 manifest.permissions 声明 `assets` 的插件才会拿到这份能力。
 */
export interface DesktopPluginAsset {
  key: string
  url: string
  bytes: number
  mime: string
  createdAt: string
}

/** 单插件资产用量；上限由宿主编译期常量决定（单文件 2 MiB、总量 64 MiB / 500 个）。 */
export interface DesktopAssetUsage {
  bytes: number
  count: number
  limitBytes: number
  limitCount: number
  limitFileBytes: number
}

/** 宿主 assets 能力：上传 / 列表 / 删除 / 用量。 */
export interface DesktopAssets {
  put(
    source: Blob | ArrayBuffer | Uint8Array,
    options?: { mime?: string },
  ): Promise<DesktopPluginAsset>
  list(): Promise<DesktopPluginAsset[]>
  delete(key: string): Promise<void>
  usage(): Promise<DesktopAssetUsage>
}

/** 宿主注入的完整 SDK 形状（能力按 manifest.permissions 可能缺失）。 */
export interface DesktopBridge {
  ready?: Promise<boolean | null>
  pluginId?: string
  storage?: DesktopStorage
  tools?: DesktopTools
  assets?: DesktopAssets
  notify?(title: string, body?: string): void
}

declare global {
  interface Window {
    desktop?: DesktopBridge
  }
}

const READY_TIMEOUT_MS = 5000
const POLL_INTERVAL_MS = 100

/** 读取当前的宿主桥；不存在时返回 null。 */
export function readDesktopBridge(): DesktopBridge | null {
  const bridge = window.desktop
  return bridge && typeof bridge === 'object' ? bridge : null
}

/** 判断桥是否真的能读写持久化数据（缺 storage 或方法不完整时按不可用处理）。 */
export function isStorageUsable(
  bridge: DesktopBridge | null,
): bridge is DesktopBridge & { storage: DesktopStorage } {
  return (
    !!bridge &&
    !!bridge.storage &&
    typeof bridge.storage.get === 'function' &&
    typeof bridge.storage.set === 'function'
  )
}

/**
 * 判断图片资产能力是否可用：老宿主没有 assets、或方法不完整时按不可用处理。
 * 调用方据此给出中文降级提示，而不是直接崩溃或静默丢弃粘贴的图片。
 *
 * 注意 try/catch：manifest 没声明 assets 时，宿主注入的是一访问属性就抛「权限不足」的
 * 代理对象（不是 undefined），所以这里不能假设读属性是安全的。
 */
export function isAssetsUsable(
  bridge: DesktopBridge | null,
): bridge is DesktopBridge & { assets: DesktopAssets } {
  if (!bridge) return false
  try {
    const assets = bridge.assets
    return (
      !!assets &&
      typeof assets.put === 'function' &&
      typeof assets.list === 'function' &&
      typeof assets.delete === 'function'
    )
  } catch {
    return false
  }
}

/** 等 ready 信号，超时视为未就绪；老版本宿主没有 ready 时直接认为可用。 */
async function waitReady(bridge: DesktopBridge, timeoutMs: number): Promise<boolean> {
  if (!bridge.ready || typeof bridge.ready.then !== 'function') return true
  return new Promise<boolean>((resolve) => {
    const timer = window.setTimeout(() => resolve(false), timeoutMs)
    bridge.ready
      ?.then((value) => {
        window.clearTimeout(timer)
        // 契约里 ready 超时会返回 null，此时视为宿主未就绪
        resolve(value === true || value === undefined)
      })
      .catch(() => {
        window.clearTimeout(timer)
        resolve(false)
      })
  })
}

/** 监听注入事件 + 轮询兜底（事件可能在监听前就派发过）。 */
function waitForInjection(timeoutMs: number): Promise<DesktopBridge | null> {
  return new Promise<DesktopBridge | null>((resolve) => {
    let settled = false

    const cleanup = (): void => {
      window.clearTimeout(timer)
      window.clearInterval(poller)
      window.removeEventListener('desktop-ready', onReadyEvent)
    }

    const finish = (bridge: DesktopBridge | null): void => {
      if (settled) return
      settled = true
      cleanup()
      resolve(bridge)
    }

    const onReadyEvent = (): void => {
      const bridge = readDesktopBridge()
      if (bridge) finish(bridge)
    }

    const poller = window.setInterval(() => {
      const bridge = readDesktopBridge()
      if (bridge) finish(bridge)
    }, POLL_INTERVAL_MS)

    const timer = window.setTimeout(() => finish(readDesktopBridge()), timeoutMs)

    window.addEventListener('desktop-ready', onReadyEvent)
  })
}

/**
 * 等待宿主 SDK 就绪：已注入则等 ready（最多 5s），未注入则等 `desktop-ready` 事件。
 * 超时返回 null，调用方据此走浏览器本地模式。
 */
export async function waitForDesktop(timeoutMs = READY_TIMEOUT_MS): Promise<DesktopBridge | null> {
  const existing = readDesktopBridge()
  if (existing) {
    const ready = await waitReady(existing, timeoutMs)
    return ready ? existing : null
  }
  const injected = await waitForInjection(timeoutMs)
  if (!injected) return null
  const ready = await waitReady(injected, timeoutMs)
  return ready ? injected : null
}

/** 安全触发宿主通知；无 notify 能力时静默。 */
export function notifyDesktop(title: string, body?: string): void {
  const bridge = readDesktopBridge()
  if (!bridge || typeof bridge.notify !== 'function') return
  try {
    bridge.notify(title, body)
  } catch (error) {
    console.warn('[note] 宿主通知失败', error)
  }
}
