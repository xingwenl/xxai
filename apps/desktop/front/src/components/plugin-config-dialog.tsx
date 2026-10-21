// 插件宿主配置弹窗：字段完全由 manifest 的 settings[] 驱动，宿主不写死任何业务字段。
// 保存成功后广播 desktop-config-changed 事件，运行中的子应用经 SDK 的 settings.onChanged 立即拿到新值。

import { useEffect, useState } from 'react'
import { getPluginConfig, savePluginConfig, type Plugin, type PluginSetting } from '../lib/api'
import { toast } from '../lib/toast'
import Dialog from './dialog'

/** 与设置页表单一致的控件样式（配置弹窗内所有类型共用） */
const FIELD_STYLE = {
  background: 'rgba(var(--hairline-rgb) / 0.05)',
  border: '1px solid rgba(var(--hairline-rgb) / 0.12)',
  color: 'var(--foreground)',
} as const

export default function PluginConfigDialog({
  plugin,
  onClose,
}: {
  /** 要配置的插件；为 null 表示弹窗关闭 */
  plugin: Plugin | null
  onClose: () => void
}) {
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const pluginId = plugin?.id ?? null

  // 每次切换插件都重新向宿主取一次配置（含 manifest 默认值），旧值不能残留到下一个插件
  useEffect(() => {
    if (!pluginId) return
    let cancelled = false
    setValues({})
    setError('')
    setLoading(true)
    getPluginConfig(pluginId)
      .then(({ values }) => {
        if (!cancelled) setValues(values)
      })
      .catch((e) => {
        if (!cancelled) setError(String((e as Error).message || e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [pluginId])

  const updateValue = (key: string, value: unknown) => {
    setValues((current) => ({ ...current, [key]: value }))
  }

  const save = async () => {
    if (!plugin) return
    setSaving(true)
    setError('')
    try {
      const { values: saved } = await savePluginConfig(plugin.id, values)
      setValues(saved)
      toast('已保存', `${plugin.name} 的配置已生效`, 'success')
      // 通知运行中的子应用：SDK 按 pluginId 过滤后回调 settings.onChanged
      window.dispatchEvent(
        new CustomEvent('desktop-config-changed', { detail: { pluginId: plugin.id, values: saved } }),
      )
      onClose()
    } catch (e) {
      // 宿主会一次返回全部校验错因（中文），弹窗保持打开让用户改
      const message = String((e as Error).message || e)
      setError(message)
      toast('保存失败', message, 'error')
    } finally {
      setSaving(false)
    }
  }

  const renderField = (setting: PluginSetting) => {
    const value = values[setting.key]
    return (
      <label key={setting.key} className="flex flex-col gap-1 text-[12px]" style={{ color: 'var(--color-mid)' }}>
        {setting.label}
        {setting.type === 'boolean' ? (
          <input
            type="checkbox"
            checked={value === true}
            onChange={(e) => updateValue(setting.key, e.target.checked)}
            className="w-4 h-4"
          />
        ) : setting.type === 'select' ? (
          <select
            value={typeof value === 'string' ? value : ''}
            onChange={(e) => updateValue(setting.key, e.target.value)}
            className="px-3 py-2 rounded-xl text-[13px] outline-none"
            style={FIELD_STYLE}
          >
            {setting.options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        ) : (
          <input
            type={setting.type === 'number' ? 'number' : 'text'}
            value={value === null || value === undefined ? '' : String(value)}
            min={setting.min ?? undefined}
            max={setting.max ?? undefined}
            onChange={(e) =>
              updateValue(
                setting.key,
                e.target.value === '' ? '' : setting.type === 'number' ? Number(e.target.value) : e.target.value,
              )
            }
            className="px-3 py-2 rounded-xl text-[13px] outline-none"
            style={FIELD_STYLE}
          />
        )}
        {setting.description && <span className="text-[11px]">{setting.description}</span>}
      </label>
    )
  }

  return (
    <Dialog
      open={plugin !== null}
      title={plugin ? `${plugin.name} 配置` : '插件配置'}
      description={plugin ? `${plugin.id} · 配置保存在本机，运行中的应用会立即收到变更` : undefined}
      width={560}
      onClose={onClose}
      footer={
        <>
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded-lg text-[12px] font-500"
            style={{ background: 'rgba(var(--surface-rgb) / 0.94)', color: 'var(--color-mid)' }}
          >
            取消
          </button>
          <button
            disabled={saving || loading}
            onClick={save}
            className="px-4 py-1.5 rounded-lg text-[12px] font-600 disabled:opacity-50"
            style={{ background: 'var(--fill-gradient)', color: 'var(--primary-foreground)' }}
          >
            {saving ? '保存中…' : '保存配置'}
          </button>
        </>
      }
    >
      {loading ? (
        <div className="text-[13px] py-6 text-center" style={{ color: 'var(--color-mid)' }}>
          读取中…
        </div>
      ) : plugin && plugin.settings.length > 0 ? (
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
          {plugin.settings.map(renderField)}
        </div>
      ) : (
        <div className="text-[13px] py-6 text-center" style={{ color: 'var(--color-mid)' }}>
          该插件没有声明 settings[]
        </div>
      )}
      {error && (
        <div className="text-[12px] mt-3 leading-relaxed" style={{ color: '#f43f5e' }}>
          {error}
        </div>
      )}
    </Dialog>
  )
}
