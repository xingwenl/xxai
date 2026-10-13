// 插件视图：iframe 沙箱加载插件页，load 后注入宿主 SDK 并触发 desktop-ready

import { useEffect, useRef } from 'react'
import { createPluginSdk } from '../lib/desktop-sdk'
import { toast } from '../lib/toast'
import type { Plugin } from '../lib/api'

/** 在系统默认浏览器打开（优先 pywebview 宿主桥，浏览器调试模式回退 window.open）。 */
async function openInBrowser(url: string) {
  const bridge = window.pywebview?.api?.open_urls
  if (bridge) {
    await bridge([url])
    return
  }
  window.open(url, '_blank', 'noopener')
}

export default function PluginView({ plugin, fullscreen }: { plugin: Plugin; fullscreen?: boolean }) {
  const frameRef = useRef<HTMLIFrameElement>(null)
  const isRemote = plugin.type === 'remote'

  useEffect(() => {
    // 远程壳插件是纯壳：不注入宿主 SDK，与浏览器标签页同等信任级别
    if (isRemote) return
    const frame = frameRef.current
    if (!frame) return

    const onLoad = () => {
      try {
        const sdk = createPluginSdk(plugin)
        const win = frame.contentWindow as (Window & { desktop?: unknown }) | null
        if (!win) throw new Error('iframe contentWindow 不可用')
        win.desktop = sdk
        if (sdk.attach) sdk.attach(frame)
        win.dispatchEvent(new CustomEvent('desktop-ready'))
      } catch (err) {
        toast('插件 SDK 注入失败', String(err), 'error')
      } finally {
        frame.classList.add('is-ready')
      }
    }

    frame.addEventListener('load', onLoad)
    return () => frame.removeEventListener('load', onLoad)
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
            border: '1px solid rgba(var(--hairline-rgb) / 0.10)',
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
      ref={frameRef}
      className={fullscreen ? 'plugin-frame plugin-frame--fullscreen' : 'plugin-frame'}
      sandbox="allow-scripts allow-same-origin allow-forms"
      src={plugin.entryUrl}
      title={plugin.name}
    />
  )
}
