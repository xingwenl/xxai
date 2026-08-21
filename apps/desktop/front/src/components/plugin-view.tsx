// 插件视图：iframe 沙箱加载插件页，load 后注入宿主 SDK 并触发 desktop-ready

import { useEffect, useRef } from 'react'
import { createPluginSdk } from '../lib/desktop-sdk'
import { toast } from '../lib/toast'
import type { Plugin } from '../lib/api'

export default function PluginView({ plugin, fullscreen }: { plugin: Plugin; fullscreen?: boolean }) {
  const frameRef = useRef<HTMLIFrameElement>(null)

  useEffect(() => {
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
  }, [plugin])

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
