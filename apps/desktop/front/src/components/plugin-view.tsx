// 插件视图：iframe 沙箱加载插件页，load 后注入宿主 SDK 并触发 desktop-ready

import { useEffect, useRef } from 'react'
import { createPluginSdk } from '../lib/desktop-sdk'
import { toast } from '../lib/toast'
import { logPluginEvent, type Plugin } from '../lib/api'
import { getRuntimeStatus, setRuntimeStatus } from '../lib/runtime-status'
import { countPluginTools, subscribeBridgeTools } from '../lib/tool-bridge'

/** 上报生命周期事件；日志通道不可用时不影响页面加载。 */
function report(pluginId: string, event: string, detail?: string): void {
  void logPluginEvent(pluginId, event, detail).catch(() => {})
}

/** 在系统默认浏览器打开（优先 pywebview 宿主桥，浏览器调试模式回退 window.open）。 */
async function openInBrowser(url: string) {
  const bridge = window.pywebview?.api?.open_urls
  if (bridge) {
    await bridge([url])
    return
  }
  window.open(url, '_blank', 'noopener')
}

export default function PluginView({
  plugin,
  fullscreen,
  reloadToken = 0,
}: {
  plugin: Plugin
  fullscreen?: boolean
  /** 开发热重载令牌：变化时通过 key 强制重建 iframe，重新加载插件目录里的最新文件 */
  reloadToken?: number
}) {
  const frameRef = useRef<HTMLIFrameElement>(null)
  const isRemote = plugin.type === 'remote'

  useEffect(() => {
    // 远程壳插件是纯壳：不注入宿主 SDK，与浏览器标签页同等信任级别
    if (isRemote) return
    const frame = frameRef.current
    if (!frame) return

    const onLoad = () => {
      report(plugin.id, 'iframe_load', plugin.entryUrl)
      try {
        const sdk = createPluginSdk(plugin)
        const win = frame.contentWindow as (Window & { desktop?: unknown }) | null
        if (!win) throw new Error('iframe contentWindow 不可用')
        win.desktop = sdk
        if (sdk.attach) sdk.attach(frame)
        win.dispatchEvent(new CustomEvent('desktop-ready'))
        report(plugin.id, 'sdk_injected')
        setRuntimeStatus(plugin.id, { state: 'ready', tools: countPluginTools(plugin.id) })
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        report(plugin.id, 'sdk_inject_failed', message)
        setRuntimeStatus(plugin.id, { state: 'failed', reason: message })
        toast('插件 SDK 注入失败', message, 'error')
      } finally {
        frame.classList.add('is-ready')
      }
    }

    // 方法注册发生在 desktop-ready 之后，订阅桥接变化以刷新「已注册方法数」
    const unsubscribe = subscribeBridgeTools(() => {
      if (getRuntimeStatus(plugin.id).state !== 'ready') return
      setRuntimeStatus(plugin.id, { state: 'ready', tools: countPluginTools(plugin.id) })
    })

    frame.addEventListener('load', onLoad)
    return () => {
      frame.removeEventListener('load', onLoad)
      unsubscribe()
    }
  }, [plugin, isRemote])

  if (isRemote) {
    const url = plugin.url || plugin.entryUrl
    return (
      <div className="relative h-full min-h-[420px]">
        <iframe
          ref={frameRef}
          className={
            (fullscreen ? 'plugin-frame plugin-frame--fullscreen' : 'plugin-frame') + ' is-ready'
          }
          sandbox="allow-scripts allow-same-origin allow-forms"
          src={url}
          title={plugin.name}
          referrerPolicy="no-referrer"
        />
        {/* 站点可能拒绝嵌入（X-Frame-Options / CSP frame-ancestors）：始终提供系统浏览器降级 */}
        <button
          onClick={() => openInBrowser(url)}
          className="absolute top-2.5 right-2.5 z-10 flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[12px] font-600"
          style={{
            background: 'rgba(var(--surface-rgb) / 0.94)',
            backdropFilter: 'blur(16px) saturate(120%)',
            WebkitBackdropFilter: 'blur(16px) saturate(120%)',
            border: '1px solid rgba(var(--hairline-rgb) / 0.12)',
            boxShadow: '0 4px 16px rgba(15,23,42,0.12)',
            color: 'var(--primary-ink)',
          }}
          title="在系统默认浏览器中打开"
        >
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-3.5 h-3.5">
            <path d="M6 3H3.5A1.5 1.5 0 0 0 2 4.5v8A1.5 1.5 0 0 0 3.5 14h8a1.5 1.5 0 0 0 1.5-1.5V10M10 2h4v4M14 2L7.5 8.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          在浏览器打开
        </button>
      </div>
    )
  }

  return (
    <iframe
      // key 变化即重建 iframe：开发热重载时让插件页重新从磁盘加载（见 App.tsx 的 revision 轮询）
      key={`${plugin.id}:${reloadToken}`}
      ref={frameRef}
      className={fullscreen ? 'plugin-frame plugin-frame--fullscreen' : 'plugin-frame'}
      sandbox="allow-scripts allow-same-origin allow-forms"
      src={plugin.entryUrl}
      title={plugin.name}
    />
  )
}
