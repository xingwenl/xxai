// 设置页：应用管理（zip 安装 / 启停 / 卸载）+ 框架信息

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  clearAgentConfig,
  getAgentConfig,
  getDesktopSettings,
  getPlugins,
  installPlugin,
  installFromUrl,
  issueAgentToken,
  refreshMetadata,
  saveAgentConfig,
  setPluginEnabled,
  uninstallPlugin,
  updatePluginMetadata,
  type AgentConfig,
  type DesktopSettings,
  type Plugin,
} from '../lib/api'
import { toast } from '../lib/toast'
import { getRuntimeStatus, subscribeRuntimeStatus } from '../lib/runtime-status'
import PageHeader from './page-header'
import PluginConfigDialog from './plugin-config-dialog'

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
  const [urlInput, setUrlInput] = useState('')
  const [urlBusy, setUrlBusy] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editDesc, setEditDesc] = useState('')
  const [editIconUrl, setEditIconUrl] = useState('')
  const [refreshBusy, setRefreshBusy] = useState(false)
  // 智能体后端（AI Base）配置：secret 不回显，留空表示沿用宿主已保存的值
  const [agentConfig, setAgentConfig] = useState<AgentConfig | null>(null)
  const [agentBaseUrl, setAgentBaseUrl] = useState('http://127.0.0.1:8000')
  const [agentClientId, setAgentClientId] = useState('')
  const [agentSecret, setAgentSecret] = useState('')
  const [agentId, setAgentId] = useState('1')
  const [agentToolNames, setAgentToolNames] = useState('')
  const [agentBusy, setAgentBusy] = useState(false)
  // 插件宿主配置（manifest.settings[]）：表单、校验与保存都在 PluginConfigDialog 弹窗里
  const [configPlugin, setConfigPlugin] = useState<Plugin | null>(null)
  // 运行态变化只用于触发重渲染，具体状态在渲染时用 getRuntimeStatus 读取
  const [, setRuntimeTick] = useState(0)

  useEffect(() => subscribeRuntimeStatus(() => setRuntimeTick((tick) => tick + 1)), [])

  const load = useCallback(() => {
    getPlugins()
      .then((d) => setPlugins(d.items))
      .catch((e) => toast('加载插件失败', String(e.message || e), 'error'))
    getDesktopSettings()
      .then(setInfo)
      .catch(() => undefined)
    getAgentConfig()
      .then((config) => {
        setAgentConfig(config)
        if (config.mode === 'remote') {
          setAgentBaseUrl(config.baseUrl || 'http://127.0.0.1:8000')
          setAgentClientId(config.clientId || '')
          setAgentId(String(config.agentId || '1'))
          setAgentToolNames((config.hostToolNames || []).join(', '))
        }
      })
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

  const handleInstallFromUrl = async () => {
    const url = urlInput.trim()
    if (!url) {
      toast('提示', '请输入要添加的网址', 'error')
      return
    }
    setUrlBusy(true)
    try {
      const { plugin, frameable } = await installFromUrl({ url })
      toast('添加成功', `${plugin.name} 已添加到应用页`, 'success')
      if (frameable === false) {
        toast('提示', '该站点可能拒绝内嵌，打开时可用「在系统浏览器打开」', 'info')
      }
      setUrlInput('')
      load()
      onChanged()
    } catch (e) {
      toast('添加失败', String((e as Error).message || e), 'error')
    } finally {
      setUrlBusy(false)
    }
  }

  const startEdit = (plugin: Plugin) => {
    setEditingId(plugin.id)
    setEditName(plugin.name)
    setEditDesc(plugin.description)
    setEditIconUrl('')
  }

  const saveEdit = async (plugin: Plugin) => {
    try {
      await updatePluginMetadata(plugin.id, {
        name: editName,
        description: editDesc,
        iconUrl: editIconUrl.trim() || undefined,
      })
      toast('已保存', plugin.name, 'success')
      setEditingId(null)
      load()
    } catch (e) {
      toast('保存失败', String((e as Error).message || e), 'error')
    }
  }

  const handleRefresh = async (plugin: Plugin) => {
    setRefreshBusy(true)
    try {
      const { plugin: updated } = await refreshMetadata(plugin.id)
      toast('已更新', `${updated.name} 元数据已重新抓取`, 'success')
      if (editingId === plugin.id) {
        setEditName(updated.name)
        setEditDesc(updated.description)
      }
      load()
    } catch (e) {
      toast('更新失败', String((e as Error).message || e), 'error')
    } finally {
      setRefreshBusy(false)
    }
  }

  const handleSaveAgent = async () => {
    const baseUrl = agentBaseUrl.trim()
    const clientId = agentClientId.trim()
    const numericAgentId = Number(agentId)
    if (!baseUrl || !clientId) {
      toast('提示', '请填写 AI Base 地址与 Embed Client ID', 'error')
      return
    }
    if (!Number.isInteger(numericAgentId) || numericAgentId < 1) {
      toast('提示', 'Agent ID 必须是正整数', 'error')
      return
    }
    const names = agentToolNames
      .split(/[\s,，]+/)
      .map((name) => name.trim())
      .filter(Boolean)
    setAgentBusy(true)
    try {
      const { config } = await saveAgentConfig({
        baseUrl,
        clientId,
        clientSecret: agentSecret.trim() || undefined,
        agentId: numericAgentId,
        hostToolNames: names.length ? names : undefined,
      })
      setAgentConfig(config)
      setAgentSecret('')
      toast('已保存', '刷新页面后助手按新配置连接', 'success')
    } catch (e) {
      toast('保存失败', String((e as Error).message || e), 'error')
    } finally {
      setAgentBusy(false)
    }
  }

  const handleTestAgent = async () => {
    setAgentBusy(true)
    try {
      const result = await issueAgentToken(window.location.origin)
      toast('连接成功', `已换发 token（有效期 ${result.expiresIn} 秒）：${result.endpoint}`, 'success')
    } catch (e) {
      toast('连接失败', String((e as Error).message || e), 'error')
    } finally {
      setAgentBusy(false)
    }
  }

  const handleClearAgent = async () => {
    if (!window.confirm('清除智能体后端配置？清除后助手回落到本地网关（若开启）或停用。')) return
    setAgentBusy(true)
    try {
      await clearAgentConfig()
      setAgentConfig({ enabled: false })
      setAgentSecret('')
      toast('已清除', '刷新页面后生效', 'success')
    } catch (e) {
      toast('清除失败', String((e as Error).message || e), 'error')
    } finally {
      setAgentBusy(false)
    }
  }

  const p = theme.primary
  const glass = {
    borderRadius: 20,
    background: 'rgba(var(--surface-rgb) / 0.88)',
    backdropFilter: 'blur(24px) saturate(120%)',
    WebkitBackdropFilter: 'blur(24px) saturate(120%)',
    border: '1px solid rgba(var(--hairline-rgb) / 0.18)',
    boxShadow: '0 4px 24px rgba(var(--shadow-rgb) / 0.08), inset 0 1px 0 rgba(255,255,255,0.8)',
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

        {/* 从 URL 添加远程壳插件 */}
        <div
          className="flex flex-wrap items-center gap-3 rounded-xl p-4 mb-3"
          style={{ background: 'rgba(var(--surface-rgb) / 0.80)', border: `1px dashed ${p}50` }}
        >
          <input
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleInstallFromUrl() }}
            placeholder="https://example.com"
            className="flex-1 min-w-[220px] px-3 py-2 rounded-xl text-[13px] outline-none"
            style={{ background: 'rgba(var(--hairline-rgb) / 0.05)', border: '1px solid rgba(var(--hairline-rgb) / 0.12)', color: 'var(--foreground)' }}
          />
          <button
            disabled={urlBusy}
            onClick={handleInstallFromUrl}
            className="px-4 py-2 rounded-xl text-[13px] font-600 disabled:opacity-50"
            style={{ background: 'var(--fill-gradient)', color: 'var(--primary-foreground)' }}
          >
            {urlBusy ? '抓取中…' : '添加应用'}
          </button>
          <span className="text-[12px] w-full" style={{ color: 'var(--color-mid)' }}>
            输入 http/https 网址（支持公网、localhost 与本机局域网地址），自动抓取名称 / 描述 / 图标安装为远程插件；可安装后编辑或重新抓取
          </span>
        </div>

        <div
          className="flex flex-wrap items-center gap-3 rounded-xl p-4"
          style={{ background: 'rgba(var(--surface-rgb) / 0.80)', border: `1px dashed ${p}50` }}
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
            className="px-4 py-2 rounded-xl text-[13px] font-600 disabled:opacity-50"
            style={{ background: 'var(--fill-gradient)', color: 'var(--primary-foreground)' }}
          >
            {busy ? '安装中…' : '安装插件（zip）'}
          </button>
          <span className="text-[12px]" style={{ color: 'var(--color-mid)' }}>
            选择 zip 插件包，安装后自动出现在应用页
          </span>
        </div>

        <div className="flex flex-col gap-2.5 mt-4">
          {plugins.map((plugin) => {
            const runtime = plugin.enabled && !plugin.error ? getRuntimeStatus(plugin.id) : { state: 'idle' as const }
            return (
            <div
              key={plugin.id}
              className="rounded-xl"
              style={{ background: 'rgba(var(--surface-rgb) / 0.88)', border: '1px solid rgba(var(--hairline-rgb) / 0.18)' }}
            >
              <div className="flex items-center gap-4 px-4 py-3">
                <div
                  className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 overflow-hidden"
                  style={{ background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)' }}
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
                      <span className="text-[10px] px-1.5 py-0.5 rounded-md font-mono" style={{ background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)' }}>
                        内置
                      </span>
                    )}
                    {plugin.type === 'remote' && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-md font-mono" style={{ background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)' }}>
                        URL
                      </span>
                    )}
                    {plugin.error && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-md font-mono" style={{ background: '#f43f5e18', color: '#f43f5e' }}>
                        异常
                      </span>
                    )}
                    {runtime.state === 'ready' && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-md font-mono" style={{ background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)' }}>
                        运行中 · {runtime.tools} 个方法
                      </span>
                    )}
                    {runtime.state === 'failed' && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-md font-mono" style={{ background: '#f43f5e18', color: '#f43f5e' }}>
                        运行失败
                      </span>
                    )}
                  </div>
                  <div className="text-[12px] truncate mt-0.5" style={{ color: 'var(--color-mid)' }}>
                    {plugin.error || `${plugin.id} · v${plugin.version}`}
                  </div>
                  {runtime.state === 'failed' && (
                    <div className="text-[11px] truncate mt-0.5" style={{ color: '#f43f5e' }}>
                      运行失败：{runtime.reason}
                    </div>
                  )}
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
                    style={{ background: plugin.enabled ? 'var(--fill)' : '#cbd5e1' }}
                  />
                </label>

                {plugin.type === 'remote' && (
                  <button
                    onClick={() => editingId === plugin.id ? setEditingId(null) : startEdit(plugin)}
                    className="px-3 py-1.5 rounded-lg text-[12px] font-500"
                    style={{ background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)' }}
                  >
                    编辑
                  </button>
                )}

                {plugin.type !== 'remote' && !plugin.error && plugin.settings.length > 0 && (
                  <button
                    onClick={() => setConfigPlugin(plugin)}
                    className="px-3 py-1.5 rounded-lg text-[12px] font-500"
                    style={{ background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)' }}
                  >
                    配置
                  </button>
                )}

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

              {/* remote 插件编辑面板：名称 / 描述 / 图标 URL + 重新抓取 */}
              {editingId === plugin.id && plugin.type === 'remote' && (
                <div
                  className="mx-4 mb-4 p-4 rounded-xl flex flex-col gap-3"
                  style={{ background: 'rgba(var(--surface-rgb) / 0.88)', border: '1px solid rgba(var(--hairline-rgb) / 0.18)' }}
                >
                  <div className="flex items-center gap-3">
                    {plugin.iconUrl && (
                      <img src={plugin.iconUrl} alt="" className="w-12 h-12 rounded-xl object-cover flex-shrink-0" />
                    )}
                    <div className="flex-1 flex flex-col gap-2">
                      <input
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        placeholder="名称"
                        className="px-3 py-2 rounded-xl text-[13px] outline-none"
                        style={{ background: 'rgba(var(--hairline-rgb) / 0.05)', border: '1px solid rgba(var(--hairline-rgb) / 0.12)', color: 'var(--foreground)' }}
                      />
                      <input
                        value={editIconUrl}
                        onChange={(e) => setEditIconUrl(e.target.value)}
                        placeholder="图标 URL（留空保持不变）"
                        className="px-3 py-2 rounded-xl text-[13px] outline-none"
                        style={{ background: 'rgba(var(--hairline-rgb) / 0.05)', border: '1px solid rgba(var(--hairline-rgb) / 0.12)', color: 'var(--foreground)' }}
                      />
                    </div>
                  </div>
                  <textarea
                    value={editDesc}
                    onChange={(e) => setEditDesc(e.target.value)}
                    placeholder="描述"
                    rows={2}
                    className="px-3 py-2 rounded-xl text-[13px] outline-none resize-none"
                    style={{ background: 'rgba(var(--hairline-rgb) / 0.05)', border: '1px solid rgba(var(--hairline-rgb) / 0.12)', color: 'var(--foreground)' }}
                  />
                  <div className="flex items-center justify-between gap-2">
                    <button
                      disabled={refreshBusy}
                      onClick={() => handleRefresh(plugin)}
                      className="px-3 py-1.5 rounded-lg text-[12px] font-500 disabled:opacity-50"
                      style={{ background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)' }}
                    >
                      {refreshBusy ? '抓取中…' : '重新抓取元数据'}
                    </button>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => setEditingId(null)}
                        className="px-3 py-1.5 rounded-lg text-[12px] font-500"
                        style={{ background: 'rgba(var(--surface-rgb) / 0.94)', color: 'var(--color-mid)' }}
                      >
                        取消
                      </button>
                      <button
                        onClick={() => saveEdit(plugin)}
                        className="px-3 py-1.5 rounded-lg text-[12px] font-600"
                        style={{ background: 'var(--fill-gradient)', color: 'var(--primary-foreground)' }}
                      >
                        保存
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
            )
          })}
          {plugins.length === 0 && (
            <div className="text-[13px] py-8 text-center" style={{ color: 'var(--color-mid)' }}>
              暂无插件，点击上方按钮安装
            </div>
          )}
        </div>
      </section>

      {/* 智能体后端：桌面助手（ai-sdk 悬浮窗）连接哪里、能用哪些方法 */}
      <section style={glass} className="p-5 mt-4">
        <div className="flex items-center justify-between gap-3 mb-2">
          <h2 className="font-600 text-[15px]" style={{ color: 'var(--foreground)' }}>智能体后端</h2>
          <span
            className="text-[11px] px-2 py-0.5 rounded-md font-mono"
            style={{
              background: agentConfig?.enabled ? 'rgba(var(--primary-ink-rgb) / 0.10)' : 'rgba(var(--hairline-rgb) / 0.10)',
              color: agentConfig?.enabled ? 'var(--primary-ink)' : 'var(--color-mid)',
            }}
          >
            {agentConfig?.mode === 'remote' ? 'AI Base' : agentConfig?.mode === 'dev' ? '本地网关' : '未配置'}
          </span>
        </div>
        <p className="text-[12px] mb-3" style={{ color: 'var(--color-mid)' }}>
          配置 AI Base 后，宿主用 Embed Client 凭证换短期 token，secret 只保存在本机；未配置时可用
          <code className="mx-1">DESKTOP_DEV_AGENT=1</code>
          启动本地网关做离线联调。
        </p>

        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
          <label className="flex flex-col gap-1 text-[12px]" style={{ color: 'var(--color-mid)' }}>
            AI Base 地址
            <input
              value={agentBaseUrl}
              onChange={(e) => setAgentBaseUrl(e.target.value)}
              placeholder="http://127.0.0.1:8000"
              className="px-3 py-2 rounded-xl text-[13px] outline-none"
              style={{ background: 'rgba(var(--hairline-rgb) / 0.05)', border: '1px solid rgba(var(--hairline-rgb) / 0.12)', color: 'var(--foreground)' }}
            />
          </label>
          <label className="flex flex-col gap-1 text-[12px]" style={{ color: 'var(--color-mid)' }}>
            Embed Client ID
            <input
              value={agentClientId}
              onChange={(e) => setAgentClientId(e.target.value)}
              placeholder="client_xxx"
              className="px-3 py-2 rounded-xl text-[13px] outline-none"
              style={{ background: 'rgba(var(--hairline-rgb) / 0.05)', border: '1px solid rgba(var(--hairline-rgb) / 0.12)', color: 'var(--foreground)' }}
            />
          </label>
          <label className="flex flex-col gap-1 text-[12px]" style={{ color: 'var(--color-mid)' }}>
            Embed Client Secret{agentConfig?.hasSecret ? '（已保存，留空沿用）' : ''}
            <input
              type="password"
              value={agentSecret}
              onChange={(e) => setAgentSecret(e.target.value)}
              placeholder={agentConfig?.hasSecret ? '不修改请留空' : '只保存在本机'}
              className="px-3 py-2 rounded-xl text-[13px] outline-none"
              style={{ background: 'rgba(var(--hairline-rgb) / 0.05)', border: '1px solid rgba(var(--hairline-rgb) / 0.12)', color: 'var(--foreground)' }}
            />
          </label>
          <label className="flex flex-col gap-1 text-[12px]" style={{ color: 'var(--color-mid)' }}>
            Agent ID
            <input
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
              placeholder="1"
              className="px-3 py-2 rounded-xl text-[13px] outline-none"
              style={{ background: 'rgba(var(--hairline-rgb) / 0.05)', border: '1px solid rgba(var(--hairline-rgb) / 0.12)', color: 'var(--foreground)' }}
            />
          </label>
        </div>

        <label className="flex flex-col gap-1 text-[12px] mt-3" style={{ color: 'var(--color-mid)' }}>
          允许调用的方法（逗号分隔；留空用默认 ledger_* 集合）
          <input
            value={agentToolNames}
            onChange={(e) => setAgentToolNames(e.target.value)}
            placeholder="ledger_add_entry, ledger_list_entries, ledger_month_summary"
            className="px-3 py-2 rounded-xl text-[13px] outline-none font-mono"
            style={{ background: 'rgba(var(--hairline-rgb) / 0.05)', border: '1px solid rgba(var(--hairline-rgb) / 0.12)', color: 'var(--foreground)' }}
          />
        </label>

        <div className="flex flex-wrap items-center gap-2 mt-4">
          <button
            disabled={agentBusy}
            onClick={handleSaveAgent}
            className="px-4 py-2 rounded-xl text-[13px] font-600 disabled:opacity-50"
            style={{ background: 'var(--fill-gradient)', color: 'var(--primary-foreground)' }}
          >
            {agentBusy ? '处理中…' : '保存配置'}
          </button>
          <button
            disabled={agentBusy || !agentConfig?.enabled}
            onClick={handleTestAgent}
            className="px-4 py-2 rounded-xl text-[13px] font-600 disabled:opacity-40"
            style={{ background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)' }}
          >
            测试连接
          </button>
          <button
            disabled={agentBusy || !agentConfig?.mode}
            onClick={handleClearAgent}
            className="px-4 py-2 rounded-xl text-[13px] font-500 disabled:opacity-40"
            style={{ background: '#f43f5e12', color: '#f43f5e' }}
          >
            清除
          </button>
          <span className="text-[12px] ml-auto" style={{ color: agentConfig?.enabled ? 'var(--color-mid)' : '#f43f5e' }}>
            {agentConfig?.reason || (agentConfig?.mode === 'remote'
              ? `Agent ${agentConfig.agentId} · ${agentConfig.clientId || ''}`
              : agentConfig?.mode === 'dev'
                ? '离线规则式网关'
                : '')}
          </span>
        </div>
      </section>

      {/* 框架信息 */}
      <section style={glass} className="p-5 mt-4">
        <h2 className="font-600 text-[15px] mb-3" style={{ color: 'var(--foreground)' }}>框架信息</h2>
        {info ? (
          <div className="flex flex-col gap-2">
            {[
              ['名称', info.name],
              ['版本', info.version],
              ['内置插件目录', info.pluginsDir],
              ['用户数据目录', info.userDataDir],
              ['插件配置目录', info.pluginConfigDir],
              ['插件日志文件', info.pluginLogFile],
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

      {/* 宿主配置弹窗：通用 Dialog 组件 + settings[] 驱动的表单 */}
      <PluginConfigDialog plugin={configPlugin} onClose={() => setConfigPlugin(null)} />
    </div>
  )
}
