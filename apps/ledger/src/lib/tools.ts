/**
 * 向桌面助手暴露的 ledger_* 方法。
 *
 * 契约：schema 与返回值形状由父级（宿主侧后台策略）依赖，字段名不要改；
 * 入参来自模型，可能缺字段或给错类型，这里统一按 unknown 收敛后再校验。
 */
import { centsToYuan, isMonth } from './format'
import type { DesktopBridge, DesktopToolDef, DesktopToolHandler } from './desktop'
import {
  addEntry,
  deleteEntry,
  listCategories,
  listEntries,
  monthSummary,
  onHostAttach,
  type EntryQuery,
} from './store'
import type { EntryType } from './types'
import toolsSchema from '../../tools.json'

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {}
}

function readString(source: Record<string, unknown>, key: string): string | undefined {
  const value = source[key]
  return typeof value === 'string' ? value : undefined
}

/** 数字入参宽松解析：兼容模型把金额写成字符串的情况。 */
function readNumber(source: Record<string, unknown>, key: string): number | undefined {
  const value = source[key]
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return undefined
}

function readEntryType(source: Record<string, unknown>): EntryType | undefined {
  const value = source.type
  return value === 'income' || value === 'expense' ? value : undefined
}

/** 显式传入月份时必须是 YYYY-MM，避免模型传「本月」之类自然语言。 */
function assertMonth(value: string | undefined): string | undefined {
  if (value === undefined) return undefined
  const trimmed = value.trim()
  if (!trimmed) return undefined
  if (!isMonth(trimmed)) throw new Error('月份格式应为 YYYY-MM')
  return trimmed
}

/** 新增记录：金额单位元，type 缺省按支出，occurred_on 缺省今天。 */
async function handleAddEntry(args: unknown): Promise<unknown> {
  const input = asRecord(args)
  const amount = readNumber(input, 'amount')
  if (amount === undefined) throw new Error('缺少金额')
  const amountCents = Math.round(amount * 100)
  if (!Number.isFinite(amountCents) || amountCents <= 0) throw new Error('金额必须大于 0')

  const entry = await addEntry({
    type: readEntryType(input) ?? 'expense',
    amount_cents: amountCents,
    category: readString(input, 'category') ?? '',
    note: readString(input, 'note') ?? '',
    occurred_on: readString(input, 'occurred_on'),
  })
  const summary = monthSummary(entry.occurred_on.slice(0, 7))

  return {
    ok: true,
    entry: {
      id: entry.id,
      type: entry.type,
      amount_yuan: centsToYuan(entry.amount_cents),
      amount_cents: entry.amount_cents,
      category: entry.category,
      note: entry.note,
      occurred_on: entry.occurred_on,
    },
    month_summary: {
      month: summary.month,
      expense_yuan: summary.expense_yuan,
      income_yuan: summary.income_yuan,
      balance_yuan: summary.balance_yuan,
    },
  }
}

/** 查询明细：默认 50 条，最多 500 条。 */
async function handleListEntries(args: unknown): Promise<unknown> {
  const input = asRecord(args)
  const query: EntryQuery = {
    month: assertMonth(readString(input, 'month')),
    type: readEntryType(input),
    category: readString(input, 'category'),
    limit: readNumber(input, 'limit'),
  }
  const result = listEntries(query)
  return {
    items: result.items.map((entry) => ({
      id: entry.id,
      type: entry.type,
      amount_yuan: entry.amount_yuan,
      category: entry.category,
      note: entry.note,
      occurred_on: entry.occurred_on,
      created_at: entry.created_at,
    })),
    total: result.total,
  }
}

/** 月度汇总：缺省当前月，by_category 按支出倒序。 */
async function handleMonthSummary(args: unknown): Promise<unknown> {
  const input = asRecord(args)
  const summary = monthSummary(assertMonth(readString(input, 'month')))
  return {
    month: summary.month,
    expense_yuan: summary.expense_yuan,
    income_yuan: summary.income_yuan,
    balance_yuan: summary.balance_yuan,
    by_category: summary.by_category.map((item) => ({
      category: item.category,
      expense_yuan: item.expense_yuan,
      income_yuan: item.income_yuan,
      count: item.count,
    })),
  }
}

/** 删除记录：不存在时抛「记录不存在」。 */
async function handleDeleteEntry(args: unknown): Promise<unknown> {
  const input = asRecord(args)
  const id = (readString(input, 'id') ?? '').trim()
  if (!id) throw new Error('记录不存在')
  await deleteEntry(id)
  return { ok: true, id }
}

/** 列出分类。 */
async function handleListCategories(): Promise<unknown> {
  return listCategories()
}

/**
 * 工具契约（名称/描述/schema/sideEffect）的唯一来源是仓库根的 `tools.json`：
 * 桌面宿主侧的 `apps/desktop/scripts/configure_ai_base.py` 读取同一份文件生成
 * 后端策略与 schema 指纹，避免两端各写一遍产生漂移。
 */
const TOOL_DEFS = toolsSchema as DesktopToolDef[]

const TOOL_NAMES = TOOL_DEFS.map((tool) => tool.name)

const HANDLERS: Record<string, DesktopToolHandler> = {
  ledger_add_entry: handleAddEntry,
  ledger_list_entries: handleListEntries,
  ledger_month_summary: handleMonthSummary,
  ledger_delete_entry: handleDeleteEntry,
  ledger_list_categories: handleListCategories,
}

let installed = false
let registeredBridge: DesktopBridge | null = null

/**
 * 注册 ledger_* 工具；宿主未提供 tools 能力或注册失败时只告警，不影响页面记账。
 * 应在 initializeLedger 之前调用，保证宿主就绪时监听已就位。
 */
export function installLedgerTools(): void {
  if (installed) return
  installed = true
  onHostAttach(async (bridge) => {
    if (registeredBridge === bridge) return
    registeredBridge = bridge
    if (!bridge.tools || typeof bridge.tools.register !== 'function') {
      console.warn('[ledger] 宿主未提供 tools 能力，跳过工具注册')
      return
    }
    try {
      await bridge.tools.register(TOOL_DEFS, HANDLERS)
    } catch (error) {
      console.warn('[ledger] 注册记账工具失败', error)
    }
  })
}

/** 注销本子应用的工具（页面卸载或热更新时可用）。 */
export async function uninstallLedgerTools(bridge: DesktopBridge | null): Promise<void> {
  if (!bridge?.tools || typeof bridge.tools.unregister !== 'function') return
  try {
    await bridge.tools.unregister(TOOL_NAMES)
  } catch (error) {
    console.warn('[ledger] 注销记账工具失败', error)
  }
}
