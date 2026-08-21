// 设置页：应用管理（zip 安装 / 启停 / 卸载）+ 框架信息

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getDesktopSettings,
  getPlugins,
  installPlugin,
  setPluginEnabled,
  uninstallPlugin,
  type DesktopSettings,
  type Plugin,
} from '../lib/api'
import { toast } from '../lib/toast'
import PageHeader from './page-header'

interface ThemeLike {
  primary: string
  gradient: [string, string]
  mid: string
  faint: string
}

export default function Settings({
  theme,
  onBack,
  onChanged,
}: {
  theme: ThemeLike
  onBack: () => void
  onChanged: () => void
}) {
  const [plugins, setPlugins] = useState<Plugin[]>([])
  const [info, setInfo] = useState<DesktopSettings | null>(null)
  const [busy, setBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = useCallback(() => {
    getPlugins()
      .then((d) => setPlugins(d.items))
      .catch((e) => toast('加载插件失败', String(e.message || e), 'error'))
    getDesktopSettings()
      .then(setInfo)
      .catch(() => undefined)
  }, [])

  useEffect(load, [load])

  const handleInstall = async (file: File) => {
    setBusy(true)
    try {
      const { plugin } = await installPlugin(file)
      toast('安装成功', `${plugin.name} v${plugin.version}`, 'success')
      load()
      onChanged()
    } catch (e) {
      toast('安装失败', String((e as Error).message || e), 'error')
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const handleToggle = async (plugin: Plugin, enabled: boolean) => {
    try {
      await setPluginEnabled(plugin.id, enabled)
      toast(enabled ? '已启用' : '已停用', plugin.name, 'success')
      load()
    } catch (e) {
      toast('操作失败', String((e as Error).message || e), 'error')
    }
  }

  const handleUninstall = async (plugin: Plugin) => {
    if (!window.confirm(`确定卸载「${plugin.name}」？`)) return
    try {
      await uninstallPlugin(plugin.id)
      toast('已卸载', plugin.name, 'success')
      load()
      onChanged()
    } catch (e) {
      toast('卸载失败', String((e as Error).message || e), 'error')
    }
  }

  const p = theme.primary
  const glass = {
    borderRadius: 20,
    background: 'rgba(255,255,255,0.5)',
    backdropFilter: 'blur(24px) saturate(180%)',
    WebkitBackdropFilter: 'blur(24px) saturate(180%)',
    border: '1px solid rgba(255,255,255,0.72)',
    boxShadow: `0 4px 24px ${p}14, inset 0 1px 0 rgba(255,255,255,0.8)`,
  } as const

  return (
    <div className="h-full overflow-y-auto" style={{ padding: '20px 28px 48px' }}>
      {/* 顶部栏（与应用页 / 插件视图共用的统一头部） */}
      <div className="sticky top-0 z-20 pb-4 pointer-events-none">
        <PageHeader
          onBack={onBack}
          icon={(
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4.5 h-4.5">
              <circle cx="10" cy="10" r="3" />
              <path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.6 4.6l1.4 1.4M14 14l1.4 1.4M15.4 4.6L14 6M6 14l-1.4 1.4" strokeLinecap="round" />
            </svg>
          )}
          title="设置"
        />
      </div>

      {/* 应用管理 */}
      <section style={glass} className="p-5 mt-4">
        <h2 className="font-600 text-[15px] mb-3" style={{ color: 'var(--foreground)' }}>应用管理</h2>

        <div
          className="flex flex-wrap items-center gap-3 rounded-xl p-4"
          style={{ background: 'rgba(255,255,255,0.4)', border: `1px dashed ${p}50` }}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".zip"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) handleInstall(file)
            }}
          />
          <button
            disabled={busy}
            onClick={() => fileRef.current?.click()}
            className="px-4 py-2 rounded-xl text-[13px] font-600 text-white disabled:opacity-50"
            style={{ background: `linear-gradient(135deg, ${theme.gradient[0]}, ${theme.gradient[1]})` }}
          >
            {busy ? '安装中…' : '安装插件（zip）'}
          </button>
          <span className="text-[12px]" style={{ color: 'var(--color-mid)' }}>
            选择 zip 插件包，安装后自动出现在应用页
          </span>
        </div>

        <div className="flex flex-col gap-2.5 mt-4">
          {plugins.map((plugin) => (
            <div
              key={plugin.id}
              className="flex items-center gap-4 rounded-xl px-4 py-3"
              style={{ background: 'rgba(255,255,255,0.45)', border: `1px solid ${p}18` }}
            >
              <div
                className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 overflow-hidden"
                style={{ background: `${p}15`, color: p }}
              >
                {plugin.iconUrl && !plugin.error ? (
                  <img src={plugin.iconUrl} alt="" className="w-10 h-10 object-cover" />
                ) : (
                  <span className="font-700 text-[14px]">{(plugin.name || '?').slice(0, 1)}</span>
                )}
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-600 text-[14px]" style={{ color: 'var(--foreground)' }}>{plugin.name}</span>
                  {plugin.builtin && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-md font-mono" style={{ background: `${p}15`, color: p }}>
                      内置
                    </span>
                  )}
                  {plugin.error && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-md font-mono" style={{ background: '#f43f5e18', color: '#f43f5e' }}>
                      异常
                    </span>
                  )}
                </div>
                <div className="text-[12px] truncate mt-0.5" style={{ color: 'var(--color-mid)' }}>
                  {plugin.error || `${plugin.id} · v${plugin.version}`}
                </div>
              </div>

              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  className="peer sr-only"
                  checked={plugin.enabled}
                  onChange={(e) => handleToggle(plugin, e.target.checked)}
                />
                <span
                  className="peer w-9 h-5 rounded-full relative transition-colors after:absolute after:left-0.5 after:top-0.5 after:w-4 after:h-4 after:rounded-full after:bg-white after:transition-transform peer-checked:after:translate-x-4"
                  style={{ background: plugin.enabled ? p : '#cbd5e1' }}
                />
              </label>

              <button
                disabled={plugin.builtin}
                onClick={() => handleUninstall(plugin)}
                title={plugin.builtin ? '内置插件不可卸载' : '卸载'}
                className="px-3 py-1.5 rounded-lg text-[12px] font-500 disabled:opacity-40"
                style={{ background: '#f43f5e12', color: plugin.builtin ? 'var(--color-mid)' : '#f43f5e' }}
              >
                卸载
              </button>
            </div>
          ))}
          {plugins.length === 0 && (
            <div className="text-[13px] py-8 text-center" style={{ color: 'var(--color-mid)' }}>
              暂无插件，点击上方按钮安装
            </div>
          )}
        </div>
      </section>

      {/* 框架信息 */}
      <section style={glass} className="p-5 mt-4">
        <h2 className="font-600 text-[15px] mb-3" style={{ color: 'var(--foreground)' }}>框架信息</h2>
        {info ? (
          <div className="flex flex-col gap-2">
            {[
              ['版本', info.version],
              ['内置插件目录', info.pluginsDir],
              ['用户数据目录', info.userDataDir],
            ].map(([k, v]) => (
              <div key={k} className="flex items-center justify-between gap-4 text-[13px]">
                <span style={{ color: 'var(--color-mid)' }}>{k}</span>
                <code className="break-all text-[12px]" style={{ color: 'var(--foreground)' }}>{v}</code>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-[13px]" style={{ color: 'var(--color-mid)' }}>加载中…</div>
        )}
      </section>
    </div>
  )
}
