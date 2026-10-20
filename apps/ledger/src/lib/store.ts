/**
 * 记账数据仓库：负责持久化、串行写入队列与订阅通知。
 *
 * 关键约束：
 * - 所有写操作进入同一条串行 Promise 队列，并在写入前重新读取持久化快照，
 *   保证「读-改-写」不会因为并发点击或工具调用而互相覆盖；
 * - 数据来源随宿主可用性切换：宿主 storage 优先，缺失时回退浏览器 localStorage；
 * - 任何状态变化都会 emit，界面订阅与工具调用共享同一份内存快照。
 */
import { isStorageUsable, readDesktopBridge, waitForDesktop, type DesktopBridge } from './desktop'
import { centsToYuan, currentMonth, isDate, isMonth, todayISO } from './format'
import {
  DEFAULT_CATEGORIES,
  emptyLedgerData,
  type EntryType,
  type LedgerData,
  type LedgerEntry,
  type LedgerEntryView,
  type MonthSummaryDetail,
} from './types'

/** 宿主 storage 的 key，落盘为 <pluginId>/ledger.json。 */
const REMOTE_KEY = 'ledger'
/** 浏览器模式下的 localStorage key。 */
const LOCAL_KEY = 'ledger:data'
const CATEGORY_MAX_LENGTH = 20
const NOTE_MAX_LENGTH = 200
const DEFAULT_LIST_LIMIT = 50
const MAX_LIST_LIMIT = 500

/** 数据落点：宿主文件 or 浏览器本地。 */
export type StorageMode = 'desktop' | 'local'

type HostListener = (bridge: DesktopBridge) => void | Promise<void>

/** 明细查询条件，字段含义与 ledger_list_entries 工具一致。 */
export interface EntryQuery {
  month?: string
  type?: EntryType
  category?: string
  limit?: number
}

/** 明细查询结果。 */
export interface EntryListResult {
  items: LedgerEntryView[]
  total: number
}

/** 新增记录入参；金额以分传入，类型缺省为支出。 */
export interface AddEntryInput {
  type?: EntryType
  amount_cents: number
  category: string
  note?: string
  occurred_on?: string
}

let data: LedgerData = emptyLedgerData()
let mode: StorageMode = 'local'
let bridge: DesktopBridge | null = null
let initPromise: Promise<void> | null = null
let writeQueue: Promise<unknown> = Promise.resolve()

const listeners = new Set<() => void>()
const hostListeners = new Set<HostListener>()

function emit(): void {
  listeners.forEach((listener) => {
    try {
      listener()
    } catch (error) {
      console.error('[ledger] 订阅回调异常', error)
    }
  })
}

/** 订阅数据变化，返回取消订阅函数（供 useSyncExternalStore 使用）。 */
export function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** 当前数据快照；只在写入后整体替换，引用稳定，可安全用于 useSyncExternalStore。 */
export function getData(): LedgerData {
  return data
}

/** 当前持久化模式，用于底部状态行。 */
export function getStorageMode(): StorageMode {
  return mode
}

/** 当前宿主桥（未注入时为 null）。 */
export function getDesktopBridge(): DesktopBridge | null {
  return bridge
}

/** 登记「宿主就绪」回调；若桥已存在会立即回调一次。 */
export function onHostAttach(listener: HostListener): void {
  if (hostListeners.has(listener)) return
  hostListeners.add(listener)
  const current = bridge ?? readDesktopBridge()
  if (current) void listener(current)
}

function cloneData(source: LedgerData): LedgerData {
  return JSON.parse(JSON.stringify(source)) as LedgerData
}

function readLocal(): LedgerData | null {
  try {
    const raw = window.localStorage.getItem(LOCAL_KEY)
    if (!raw) return null
    return normalizeData(JSON.parse(raw) as unknown)
  } catch (error) {
    console.warn('[ledger] 读取浏览器本地数据失败', error)
    return null
  }
}

function writeLocal(next: LedgerData): void {
  try {
    window.localStorage.setItem(LOCAL_KEY, JSON.stringify(next))
  } catch (error) {
    console.warn('[ledger] 写入浏览器本地数据失败', error)
  }
}

async function readRemote(source: DesktopBridge): Promise<LedgerData | null> {
  if (!isStorageUsable(source)) return null
  try {
    return normalizeData(await source.storage.get(REMOTE_KEY))
  } catch (error) {
    console.warn('[ledger] 读取宿主持久化数据失败', error)
    return null
  }
}

async function readPersisted(): Promise<LedgerData | null> {
  if (isStorageUsable(bridge)) return readRemote(bridge)
  return readLocal()
}

async function persist(next: LedgerData): Promise<void> {
  if (isStorageUsable(bridge)) {
    await bridge.storage.set(REMOTE_KEY, next)
    return
  }
  writeLocal(next)
}

/** 串行队列：无论上一个任务成败都要把后续任务接上。 */
function enqueue<T>(task: () => Promise<T>): Promise<T> {
  const run = writeQueue.then(task, task)
  writeQueue = run.then(
    () => undefined,
    () => undefined,
  )
  return run
}

/** 统一的读-改-写：重新读持久化 → 改副本 → 落盘 → 更新内存 → 广播。 */
async function mutate<T>(mutator: (draft: LedgerData) => T): Promise<T> {
  return enqueue(async () => {
    const latest = await readPersisted()
    const draft = cloneData(latest ?? data)
    const result = mutator(draft)
    draft.updated_at = new Date().toISOString()
    await persist(draft)
    data = draft
    emit()
    return result
  })
}

function mergeCategories(type: EntryType, raw: unknown): string[] {
  const result = [...DEFAULT_CATEGORIES[type]]
  if (!Array.isArray(raw)) return result
  for (const item of raw) {
    if (typeof item !== 'string') continue
    const name = item.trim()
    if (name && !result.includes(name)) result.push(name)
  }
  return result
}

function normalizeCategories(raw: unknown): LedgerData['categories'] {
  const record = (typeof raw === 'object' && raw !== null ? raw : {}) as Record<string, unknown>
  return {
    expense: mergeCategories('expense', record.expense),
    income: mergeCategories('income', record.income),
  }
}

function newId(): string {
  const cryptoApi = globalThis.crypto
  if (cryptoApi && typeof cryptoApi.randomUUID === 'function') return cryptoApi.randomUUID()
  return `entry-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function toEntry(raw: unknown): LedgerEntry | null {
  if (typeof raw !== 'object' || raw === null) return null
  const record = raw as Record<string, unknown>
  const cents =
    typeof record.amount_cents === 'number' && Number.isFinite(record.amount_cents)
      ? Math.round(record.amount_cents)
      : 0
  // 金额非法的记录直接丢弃，宁可少一条也不要污染汇总
  if (cents <= 0) return null
  const fallbackDate =
    typeof record.created_at === 'string' && isDate(record.created_at.slice(0, 10))
      ? record.created_at.slice(0, 10)
      : todayISO()
  const occurredOn =
    typeof record.occurred_on === 'string' && isDate(record.occurred_on)
      ? record.occurred_on
      : fallbackDate
  return {
    id: typeof record.id === 'string' && record.id ? record.id : newId(),
    type: record.type === 'income' ? 'income' : 'expense',
    amount_cents: cents,
    category:
      typeof record.category === 'string' && record.category.trim() ? record.category.trim() : '其他',
    note: typeof record.note === 'string' ? record.note : '',
    occurred_on: occurredOn,
    created_at:
      typeof record.created_at === 'string' && record.created_at
        ? record.created_at
        : new Date().toISOString(),
  }
}

/** 把任意来源的数据收敛成合法快照；非对象返回 null 表示「没有数据」。 */
function normalizeData(raw: unknown): LedgerData | null {
  if (typeof raw !== 'object' || raw === null) return null
  const record = raw as Record<string, unknown>
  const entries = Array.isArray(record.entries)
    ? record.entries.map(toEntry).filter((entry): entry is LedgerEntry => entry !== null)
    : []
  return {
    version: 1,
    entries,
    categories: normalizeCategories(record.categories),
    updated_at:
      typeof record.updated_at === 'string' ? record.updated_at : new Date().toISOString(),
  }
}

async function notifyHost(detected: DesktopBridge): Promise<void> {
  for (const listener of hostListeners) {
    try {
      await listener(detected)
    } catch (error) {
      console.warn('[ledger] 宿主能力注册失败', error)
    }
  }
}

/** 宿主就绪后接管数据：优先用宿主快照，其次把浏览器本地数据迁移过去。 */
async function attachHost(detected: DesktopBridge): Promise<void> {
  if (bridge === detected) return
  bridge = detected

  if (!isStorageUsable(detected)) {
    console.warn('[ledger] 宿主未提供 storage 能力，继续使用浏览器本地存储')
    emit()
    await notifyHost(detected)
    return
  }

  const remote = await readRemote(detected)
  mode = 'desktop'
  if (remote) {
    data = remote
  } else {
    // 宿主首次使用：浏览器里已有的账目不能丢，整体迁移过去
    const local = readLocal()
    if (local && local.entries.length > 0) {
      data = local
      await persist(local)
      console.info('[ledger] 已将浏览器本地数据迁移到宿主持久化')
    } else {
      data = emptyLedgerData()
    }
  }
  emit()
  await notifyHost(detected)
}

function handleDesktopReady(): void {
  const detected = readDesktopBridge()
  if (detected) void attachHost(detected)
}

async function bootstrap(): Promise<void> {
  // 先同步渲染浏览器本地数据，避免宿主 5s 就绪等待期里页面空白
  const local = readLocal()
  if (local) data = local
  emit()

  window.addEventListener('desktop-ready', handleDesktopReady)
  const detected = await waitForDesktop()
  if (detected) await attachHost(detected)
}

/** 启动仓库：加载本地数据并尝试接入宿主；重复调用返回同一个 Promise。 */
export function initializeLedger(): Promise<void> {
  if (!initPromise) initPromise = bootstrap()
  return initPromise
}

/** 重新从持久化层拉取快照（顶部「刷新」按钮用）。 */
export async function refreshLedger(): Promise<void> {
  return enqueue(async () => {
    const latest = await readPersisted()
    if (!latest) return
    data = latest
    emit()
  })
}

function ensureCategory(list: string[], name: string): void {
  if (!list.includes(name)) list.push(name)
}

/** 新增一条记录，顺带把自定义分类登记进分类表。 */
export async function addEntry(input: AddEntryInput): Promise<LedgerEntry> {
  const type: EntryType = input.type === 'income' ? 'income' : 'expense'
  const cents = Math.round(input.amount_cents)
  if (!Number.isFinite(cents) || cents <= 0) throw new Error('金额必须大于 0')

  const defaults = DEFAULT_CATEGORIES[type]
  const category = (input.category || '').trim() || defaults[defaults.length - 1]
  const occurredOn = (input.occurred_on || todayISO()).trim()
  if (!isDate(occurredOn)) throw new Error('日期格式应为 YYYY-MM-DD')
  const note = (input.note ?? '').trim().slice(0, NOTE_MAX_LENGTH)

  const entry: LedgerEntry = {
    id: newId(),
    type,
    amount_cents: cents,
    category,
    note,
    occurred_on: occurredOn,
    created_at: new Date().toISOString(),
  }

  return mutate((draft) => {
    draft.entries.push(entry)
    ensureCategory(draft.categories[type], category)
    return entry
  })
}

/** 删除一条记录；不存在时抛错，供工具层原样透出中文提示。 */
export async function deleteEntry(id: string): Promise<void> {
  if (!id) throw new Error('记录不存在')
  return mutate((draft) => {
    const index = draft.entries.findIndex((entry) => entry.id === id)
    if (index < 0) throw new Error('记录不存在')
    draft.entries.splice(index, 1)
  })
}

/** 新增自定义分类（重复则去重），返回该类型的最新分类列表。 */
export async function addCategory(type: EntryType, raw: string): Promise<string[]> {
  const name = raw.trim().replace(/\s+/g, ' ')
  if (!name) throw new Error('请输入分类名称')
  if (name.length > CATEGORY_MAX_LENGTH) {
    throw new Error(`分类名称不能超过 ${CATEGORY_MAX_LENGTH} 个字`)
  }
  return mutate((draft) => {
    ensureCategory(draft.categories[type], name)
    return [...draft.categories[type]]
  })
}

function compareEntries(a: LedgerEntry, b: LedgerEntry): number {
  if (a.occurred_on !== b.occurred_on) return a.occurred_on < b.occurred_on ? 1 : -1
  if (a.created_at !== b.created_at) return a.created_at < b.created_at ? 1 : -1
  return 0
}

function toView(entry: LedgerEntry): LedgerEntryView {
  return { ...entry, amount_yuan: centsToYuan(entry.amount_cents) }
}

/** 按条件查询明细：发生日期倒序、同日按创建时间倒序；total 为未受 limit 限制的总数。 */
export function listEntries(query: EntryQuery = {}): EntryListResult {
  const month = query.month && isMonth(query.month) ? query.month : undefined
  const rawLimit = Math.trunc(query.limit ?? DEFAULT_LIST_LIMIT)
  const limit = Math.min(Math.max(Number.isFinite(rawLimit) && rawLimit > 0 ? rawLimit : DEFAULT_LIST_LIMIT, 1), MAX_LIST_LIMIT)

  const matched = data.entries.filter((entry) => {
    if (month && !entry.occurred_on.startsWith(month)) return false
    if (query.type && entry.type !== query.type) return false
    if (query.category && entry.category !== query.category) return false
    return true
  })

  const sorted = [...matched].sort(compareEntries)
  return { items: sorted.slice(0, limit).map(toView), total: matched.length }
}

/** 月度汇总（含分类拆分，按支出金额倒序）；非法月份回退到当前月。 */
export function monthSummary(month = currentMonth()): MonthSummaryDetail {
  const target = isMonth(month) ? month : currentMonth()
  let expenseCents = 0
  let incomeCents = 0
  const buckets = new Map<string, { expense: number; income: number; count: number }>()

  for (const entry of data.entries) {
    if (!entry.occurred_on.startsWith(target)) continue
    const bucket = buckets.get(entry.category) ?? { expense: 0, income: 0, count: 0 }
    if (entry.type === 'income') {
      bucket.income += entry.amount_cents
      incomeCents += entry.amount_cents
    } else {
      bucket.expense += entry.amount_cents
      expenseCents += entry.amount_cents
    }
    bucket.count += 1
    buckets.set(entry.category, bucket)
  }

  const byCategory = [...buckets.entries()]
    .map(([category, bucket]) => ({
      category,
      expense_yuan: centsToYuan(bucket.expense),
      income_yuan: centsToYuan(bucket.income),
      count: bucket.count,
    }))
    .sort(
      (a, b) =>
        b.expense_yuan - a.expense_yuan ||
        b.income_yuan - a.income_yuan ||
        a.category.localeCompare(b.category, 'zh-Hans-CN'),
    )

  return {
    month: target,
    expense_yuan: centsToYuan(expenseCents),
    income_yuan: centsToYuan(incomeCents),
    balance_yuan: centsToYuan(incomeCents - expenseCents),
    by_category: byCategory,
  }
}

/** 当前分类表（返回副本，避免调用方改到内存快照）。 */
export function listCategories(): { expense: string[]; income: string[] } {
  return { expense: [...data.categories.expense], income: [...data.categories.income] }
}
