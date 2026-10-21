// 宿主 SDK（TypeScript 版）：注入插件 iframe 的 window.desktop
// 契约与静态版一致：宿主在 iframe load 后注入并触发 desktop-ready 事件

import {
  deletePluginData,
  getDesktopSettings,
  getPluginConfig,
  getPluginData,
  getPlugins,
  listPluginDataKeys,
  proxyFetch,
  setPluginData,
  type Plugin,
} from './api'
import { registerPluginTools, unregisterPluginTools, type HostToolDefinition, type HostToolHandler } from './tool-bridge'
import { toast } from './toast'

const LS_SETTINGS_PREFIX = 'desktop:settings:'

export interface DesktopSdk {
  ready: Promise<boolean>
  pluginId: string
  pluginName: string
  appInfo(): Promise<{ name: string; version: string; plugin: { id: string; name: string; version: string } }>
  getApps(): Promise<Plugin[]>
  navigate(path: string): void
  openApp(id: string): void
  /** 支持 `notify({title, body})` 与 `notify(title, body)` 两种写法（后者是记账等新插件契约）。 */
  notify?(opts: { title?: string; body?: string } | string, body?: string): void
  settings?: {
    get(key: string, fallback?: unknown): unknown
    set(key: string, value: unknown): void
    /** 读取宿主配置：manifest.settings[] 的默认值与已保存值合并后的完整取值。 */
    getConfig(): Promise<Record<string, unknown>>
    /** 监听宿主配置变更（设置页保存后触发）；返回取消订阅函数。 */
    onChanged(handler: (values: Record<string, unknown>) => void): () => void
  }
  /** 子应用本地数据：由宿主落盘（plugin-data），全异步。 */
  storage?: {
    get(key: string, fallback?: unknown): Promise<unknown>
    set(key: string, value: unknown): Promise<void>
    delete(key: string): Promise<void>
    keys(): Promise<string[]>
  }
  /** 向全局助手注册可调用方法（manifest.permissions 需声明 tools）。 */
  tools?: {
    register(defs: HostToolDefinition[], handlers: Record<string, HostToolHandler>): Promise<void>
    unregister(names: string[]): Promise<void>
  }
  events?: {
    on(event: string, handler: (payload: unknown, meta: { source: string }) => void): () => void
    emit(event: string, payload?: unknown): void
  }
  http?: { get(url: string, opts?: Record<string, unknown>): Promise<unknown>; post(url: string, opts?: Record<string, unknown>): Promise<unknown> }
  platform?: { info(): Promise<unknown> }
  log?: { info(...args: unknown[]): void; warn(...args: unknown[]): void; error(...args: unknown[]): void }
  attach?(iframe: HTMLIFrameElement): void
}

/** 未声明权限的能力返回抛错代理：插件以方法形式访问（如 settings.get）时给出明确错误。 */
function denied<T>(ability: string): T {
  return new Proxy({}, {
    get() {
      throw new Error(`权限不足：manifest.permissions 未声明 ${ability}`)
    },
  }) as T
}

function readJson(key: string, fallback: unknown): unknown {
  const raw = localStorage.getItem(key)
  if (raw === null) return fallback
  try {
    return JSON.parse(raw)
  } catch {
    return fallback
  }
}

function writeJson(key: string, value: unknown): void {
  localStorage.setItem(key, JSON.stringify(value))
}

export function createPluginSdk(plugin: Plugin): DesktopSdk {
  const perms = new Set(plugin.permissions || [])
  const handlers = new Map<string, Set<(payload: unknown, meta: { source: string }) => void>>()

  const sdk: DesktopSdk = {
    ready: Promise.resolve(true),
    pluginId: plugin.id,
    pluginName: plugin.name,

    async appInfo() {
      const settings = await getDesktopSettings()
      return {
        name: settings.name,
        version: settings.version,
        plugin: { id: plugin.id, name: plugin.name, version: plugin.version },
      }
    },

    getApps() {
      return getPlugins().then((d) => d.items)
    },

    navigate(path: string) {
      window.location.hash = path
    },

    openApp(id: string) {
      window.location.hash = `#/app/${encodeURIComponent(id)}`
    },
  }

  if (perms.has('notify')) {
    sdk.notify = (opts, body) => {
      if (typeof opts === 'string') {
        toast(opts, body || '')
        return
      }
      toast(opts.title || plugin.name, opts.body || '')
    }
  } else {
    sdk.notify = denied('notify')
  }

  if (perms.has('settings')) {
    const configHandlers = new Set<(values: Record<string, unknown>) => void>()
    // 配置变更由宿主的设置页在保存成功后派发；SDK 在宿主窗口监听并按插件 id 过滤，
    // 因为设置页改的是宿主配置，插件 iframe 没有写入通道（只读）。
    const onConfigChanged = (ev: Event) => {
      const detail = (ev as CustomEvent<{ pluginId?: string; values?: Record<string, unknown> }>).detail
      if (!detail || detail.pluginId !== plugin.id || !detail.values) return
      configHandlers.forEach((handler) => {
        try {
          handler(detail.values!)
        } catch (err) {
          console.error('[desktop:config] handler 异常', err)
        }
      })
    }
    window.addEventListener('desktop-config-changed', onConfigChanged)
    sdk.settings = {
      get: (key, fallback = null) => readJson(LS_SETTINGS_PREFIX + plugin.id + ':' + key, fallback),
      set: (key, value) => writeJson(LS_SETTINGS_PREFIX + plugin.id + ':' + key, value),
      async getConfig() {
        return (await getPluginConfig(plugin.id)).values
      },
      onChanged(handler) {
        configHandlers.add(handler)
        return () => configHandlers.delete(handler)
      },
    }
  } else {
    sdk.settings = denied('settings')
  }

  if (perms.has('storage')) {
    // 数据落宿主 ~/.desktop-app/plugin-data/<pluginId>/<key>.json：
    // 与浏览器 localStorage 不同，它是子应用真实数据，卸载宿主以外的清理责任在宿主。
    sdk.storage = {
      async get(key, fallback = null) {
        const value = await getPluginData(plugin.id, key)
        return value === null ? fallback : value
      },
      async set(key, value) {
        await setPluginData(plugin.id, key, value)
      },
      async delete(key) {
        await deletePluginData(plugin.id, key)
      },
      async keys() {
        return (await listPluginDataKeys(plugin.id)).keys
      },
    }
  } else {
    sdk.storage = denied('storage')
  }

  if (perms.has('tools')) {
    sdk.tools = {
      async register(defs, handlers) {
        registerPluginTools(plugin, defs, handlers)
      },
      async unregister(names) {
        unregisterPluginTools(plugin.id, names)
      },
    }
  } else {
    sdk.tools = denied('tools')
  }

  if (perms.has('events')) {
    sdk.events = {
      on(event, handler) {
        if (!handlers.has(event)) handlers.set(event, new Set())
        handlers.get(event)!.add(handler)
        return () => handlers.get(event)!.delete(handler)
      },
      emit(event, payload) {
        window.postMessage({ type: 'desktop:event', source: plugin.id, event, payload }, '*')
      },
    }
    sdk.attach = (iframe) => {
      iframe.contentWindow?.addEventListener('message', (ev) => {
        const data = ev.data as { type?: string; event?: string; payload?: unknown; source?: string }
        if (!data || data.type !== 'desktop:event' || !data.event) return
        const set = handlers.get(data.event)
        if (!set) return
        set.forEach((handler) => {
          try {
            handler(data.payload, { source: data.source || '' })
          } catch (err) {
            console.error('[desktop:event] handler 异常', err)
          }
        })
      })
    }
  } else {
    sdk.events = denied('events')
  }

  if (perms.has('http')) {
    sdk.http = {
      get: (url, opts) => proxyFetch('GET', url, opts?.body as unknown),
      post: (url, opts) => proxyFetch('POST', url, opts?.body as unknown),
    }
  } else {
    sdk.http = denied('http')
  }

  if (perms.has('platform')) {
    sdk.platform = {
      async info() {
        const settings = await getDesktopSettings()
        return { ...settings, os: navigator.platform, language: navigator.language }
      },
    }
  } else {
    sdk.platform = denied('platform')
  }

  if (perms.has('log')) {
    const tag = `[plugin:${plugin.id}]`
    sdk.log = {
      info: (...args) => console.log(tag, ...args),
      warn: (...args) => console.warn(tag, ...args),
      error: (...args) => console.error(tag, ...args),
    }
  } else {
    sdk.log = denied('log')
  }

  return sdk
}
