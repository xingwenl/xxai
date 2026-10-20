import { useCallback, useEffect, useMemo, useState, useSyncExternalStore, type FormEvent } from 'react'
import { notifyDesktop } from './lib/desktop'
import { currentMonth, formatCents, formatDateLabel, formatMoney, todayISO } from './lib/format'
import {
  addCategory,
  addEntry,
  deleteEntry,
  getData,
  getStorageMode,
  listEntries,
  monthSummary,
  refreshLedger,
  subscribe,
} from './lib/store'
import type { EntryType } from './lib/types'

const TYPE_LABEL: Record<EntryType, string> = { expense: '支出', income: '收入' }
/** 明细一次查询上限；界面按月展示，500 条足够覆盖正常使用。 */
const LIST_LIMIT = 500
const NEW_CATEGORY_VALUE = '__new_category__'

/** 把 unknown 异常收敛成可展示的中文提示。 */
function messageOf(error: unknown): string {
  return error instanceof Error && error.message ? error.message : '操作失败，请稍后重试'
}

/**
 * 记账单页：顶部月份切换 + 三张汇总卡片 + 记一笔表单 + 当月明细。
 * 数据来自 store，任何写入（界面或工具调用）都会通过 subscribe 回到这里。
 */
export default function App() {
  const data = useSyncExternalStore(subscribe, getData, getData)
  const mode = useSyncExternalStore(subscribe, getStorageMode, getStorageMode)

  const [month, setMonth] = useState(currentMonth)
  const [type, setType] = useState<EntryType>('expense')
  const [amount, setAmount] = useState('')
  const [category, setCategory] = useState('')
  const [note, setNote] = useState('')
  const [occurredOn, setOccurredOn] = useState(todayISO)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)

  const [addingCategory, setAddingCategory] = useState(false)
  const [newCategory, setNewCategory] = useState('')
  const [categoryError, setCategoryError] = useState('')

  const [listError, setListError] = useState('')
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const categories = data.categories[type]
  const summary = useMemo(() => monthSummary(month), [data, month])
  const entries = useMemo(() => listEntries({ month, limit: LIST_LIMIT }), [data, month])

  // 分类列表变化（切类型、新增分类、宿主数据落定）后，保证下拉值始终有效
  useEffect(() => {
    if (!categories.includes(category)) setCategory(categories[0] ?? '其他')
  }, [categories, category])

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      setFormError('')

      const text = amount.trim()
      if (!text) {
        setFormError('请输入金额')
        return
      }
      if (!/^\d+(\.\d{1,2})?$/.test(text)) {
        setFormError('金额格式不正确，最多两位小数')
        return
      }
      const yuan = Number(text)
      if (!Number.isFinite(yuan) || yuan <= 0) {
        setFormError('金额必须大于 0')
        return
      }
      if (!occurredOn) {
        setFormError('请选择记账日期')
        return
      }

      setSaving(true)
      try {
        const entry = await addEntry({
          type,
          amount_cents: Math.round(yuan * 100),
          category: category || categories[0] || '其他',
          note,
          occurred_on: occurredOn,
        })
        notifyDesktop(
          '记账成功',
          `${TYPE_LABEL[entry.type]} ¥${formatCents(entry.amount_cents)} · ${entry.category}`,
        )
        setAmount('')
        setNote('')
        // 记到别的月份时顺手切过去，避免用户以为没保存
        setMonth(entry.occurred_on.slice(0, 7))
      } catch (error) {
        setFormError(messageOf(error))
      } finally {
        setSaving(false)
      }
    },
    [amount, occurredOn, type, category, categories, note],
  )

  const handleDelete = useCallback(async (id: string) => {
    setListError('')
    setDeletingId(id)
    try {
      await deleteEntry(id)
      notifyDesktop('已删除', '记账记录已删除')
    } catch (error) {
      setListError(messageOf(error))
    } finally {
      setDeletingId(null)
    }
  }, [])

  const handleRefresh = useCallback(async () => {
    setListError('')
    setRefreshing(true)
    try {
      await refreshLedger()
    } catch (error) {
      setListError(messageOf(error))
    } finally {
      setRefreshing(false)
    }
  }, [])

  const handleCategorySelect = useCallback(
    (value: string) => {
      if (value === NEW_CATEGORY_VALUE) {
        setAddingCategory(true)
        setCategoryError('')
        return
      }
      setCategory(value)
    },
    [],
  )

  const handleConfirmCategory = useCallback(async () => {
    setCategoryError('')
    const name = newCategory.trim()
    if (!name) {
      setCategoryError('请输入分类名称')
      return
    }
    try {
      const list = await addCategory(type, name)
      if (list.includes(name)) setCategory(name)
      setNewCategory('')
      setAddingCategory(false)
    } catch (error) {
      setCategoryError(messageOf(error))
    }
  }, [newCategory, type])

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <h1>记账</h1>
          <p className="subtitle">记下每一笔，月底看清钱花在哪</p>
        </div>
        <div className="header-actions">
          <label className="month-picker">
            <span className="sr-only">选择月份</span>
            <input
              type="month"
              value={month}
              onChange={(event) => setMonth(event.target.value || currentMonth())}
            />
          </label>
          <button
            type="button"
            className="button ghost"
            onClick={() => void handleRefresh()}
            disabled={refreshing}
          >
            {refreshing ? '刷新中…' : '刷新'}
          </button>
        </div>
      </header>

      <section className="cards" aria-label="本月汇总">
        <article className="card card-expense">
          <span className="card-label">本月支出</span>
          <strong className="card-value">{formatMoney(summary.expense_yuan)}</strong>
        </article>
        <article className="card card-income">
          <span className="card-label">本月收入</span>
          <strong className="card-value">{formatMoney(summary.income_yuan)}</strong>
        </article>
        <article className={`card card-balance${summary.balance_yuan < 0 ? ' is-negative' : ''}`}>
          <span className="card-label">结余</span>
          <strong className="card-value">{formatMoney(summary.balance_yuan)}</strong>
        </article>
      </section>

      <section className="panel" aria-label="记一笔">
        <h2 className="panel-title">记一笔</h2>
        <form className="form" onSubmit={(event) => void handleSubmit(event)}>
          <div className="segmented" role="group" aria-label="类型">
            {(['expense', 'income'] as const).map((item) => (
              <button
                key={item}
                type="button"
                className={`segment${type === item ? ' is-active' : ''}`}
                aria-pressed={type === item}
                onClick={() => {
                  setType(item)
                  setFormError('')
                }}
              >
                {TYPE_LABEL[item]}
              </button>
            ))}
          </div>

          <div className="field">
            <label htmlFor="amount">金额（元）</label>
            <input
              id="amount"
              type="number"
              step="0.01"
              min="0"
              inputMode="decimal"
              placeholder="0.00"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          </div>

          <div className="field">
            <label htmlFor="category">分类</label>
            <select
              id="category"
              value={category}
              onChange={(event) => handleCategorySelect(event.target.value)}
            >
              {categories.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
              <option value={NEW_CATEGORY_VALUE}>＋ 新增分类</option>
            </select>
          </div>

          <div className="field">
            <label htmlFor="occurred-on">日期</label>
            <input
              id="occurred-on"
              type="date"
              value={occurredOn}
              onChange={(event) => setOccurredOn(event.target.value)}
            />
          </div>

          <div className="field field-wide">
            <label htmlFor="note">备注</label>
            <input
              id="note"
              type="text"
              maxLength={200}
              placeholder="可选，例如「午饭」"
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </div>

          {addingCategory && (
            <div className="field field-wide category-editor">
              <label htmlFor="new-category">新增{TYPE_LABEL[type]}分类</label>
              <div className="inline">
                <input
                  id="new-category"
                  type="text"
                  maxLength={20}
                  placeholder="例如：宠物"
                  value={newCategory}
                  onChange={(event) => setNewCategory(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault()
                      void handleConfirmCategory()
                    }
                  }}
                />
                <button type="button" className="button primary" onClick={() => void handleConfirmCategory()}>
                  确认
                </button>
                <button
                  type="button"
                  className="button ghost"
                  onClick={() => {
                    setAddingCategory(false)
                    setNewCategory('')
                    setCategoryError('')
                  }}
                >
                  取消
                </button>
              </div>
              {categoryError && <p className="field-error">{categoryError}</p>}
            </div>
          )}

          <div className="form-actions">
            {formError ? (
              <p className="form-error" role="alert">
                {formError}
              </p>
            ) : (
              <span className="form-hint">金额最多两位小数，数据只保存在本地</span>
            )}
            <button type="submit" className="button primary" disabled={saving}>
              {saving ? '保存中…' : '保存'}
            </button>
          </div>
        </form>
      </section>

      <section className="panel" aria-label="明细">
        <div className="panel-head">
          <h2 className="panel-title">明细</h2>
          <span className="panel-meta">{entries.total} 条</span>
        </div>

        {listError && (
          <p className="form-error" role="alert">
            {listError}
          </p>
        )}

        {entries.items.length === 0 ? (
          <p className="empty">本月还没有记录</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">日期</th>
                  <th scope="col">分类</th>
                  <th scope="col">备注</th>
                  <th scope="col" className="num">
                    金额
                  </th>
                  <th scope="col" className="col-action">
                    <span className="sr-only">操作</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {entries.items.map((entry) => (
                  <tr key={entry.id}>
                    <td className="col-date">{formatDateLabel(entry.occurred_on)}</td>
                    <td>
                      <span className={`tag tag-${entry.type}`}>{TYPE_LABEL[entry.type]}</span>
                      {entry.category}
                    </td>
                    <td className="col-note">{entry.note || '—'}</td>
                    <td className={`num amount amount-${entry.type}`}>
                      {entry.type === 'income' ? '+' : '-'}¥{formatCents(entry.amount_cents)}
                    </td>
                    <td className="col-action">
                      <button
                        type="button"
                        className="button link-danger"
                        disabled={deletingId === entry.id}
                        onClick={() => void handleDelete(entry.id)}
                      >
                        {deletingId === entry.id ? '删除中' : '删除'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <footer className="statusbar">
        <span className={`dot${mode === 'desktop' ? ' is-online' : ''}`} aria-hidden="true" />
        <span>{mode === 'desktop' ? '本地数据（宿主持久化）' : '浏览器本地（未连接桌面宿主）'}</span>
      </footer>
    </div>
  )
}
