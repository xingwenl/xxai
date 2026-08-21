// 宿主 SDK（TypeScript 版）：注入插件 iframe 的 window.desktop
// 契约与静态版一致：宿主在 iframe load 后注入并触发 desktop-ready 事件

import { getDesktopSettings, getPlugins, proxyFetch, type Plugin } from './api'
import { toast } from './toast'

const LS_SETTINGS_PREFIX = 'desktop:settings:'
const LS_STORAGE_PREFIX = 'desktop:storage:'

export interface DesktopSdk {
  ready: Promise<boolean>
  pluginId: string
  pluginName: string
  appInfo(): Promise<{ name: string; version: string; plugin: { id: string; name: string; version: string } }>
  getApps(): Promise<Plugin[]>
  navigate(path: string): void
  openApp(id: string): void
  notify?(opts: { title?: string; body?: string }): void
  settings?: { get(key: string, fallback?: unknown): unknown; set(key: string, value: unknown): void }
  storage?: { get(key: string, fallback?: unknown): unknown; set(key: string, value: unknown): void }
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
    sdk.notify = (opts) => toast(opts.title || plugin.name, opts.body || '')
  } else {
    sdk.notify = denied('notify')
  }

  if (perms.has('settings')) {
    sdk.settings = {
      get: (key, fallback = null) => readJson(LS_SETTINGS_PREFIX + plugin.id + ':' + key, fallback),
      set: (key, value) => writeJson(LS_SETTINGS_PREFIX + plugin.id + ':' + key, value),
    }
  } else {
    sdk.settings = denied('settings')
  }

  if (perms.has('storage')) {
    sdk.storage = {
      get: (key, fallback = null) => readJson(LS_STORAGE_PREFIX + plugin.id + ':' + key, fallback),
      set: (key, value) => writeJson(LS_STORAGE_PREFIX + plugin.id + ':' + key, value),
    }
  } else {
    sdk.storage = denied('storage')
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
