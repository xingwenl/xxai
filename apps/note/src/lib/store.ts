/**
 * 笔记数据仓库：持久化、串行写队列、宿主迁移与订阅通知。
 *
 * 关键约束：
 * - 所有写操作进入同一条串行 Promise 队列，写入前重新读取持久化快照，
 *   保证「读-改-写」不会被并发点击或 AI 工具调用互相覆盖；
 * - 持久化优先用宿主 storage（`note` key → plugin-data/note/note.json），
 *   无宿主时降级到 localStorage('note:data')，宿主首次可用时把本地数据整体迁移过去；
 * - 内存快照只在写入成功后整体替换，引用稳定，供 useSyncExternalStore 直接使用；
 * - 超限策略：标题/分类/正文超长一律**截断**（不抛错，避免用户整篇笔记保存失败），
 *   但整份 JSON 超过宿主单值上限 256 KiB 时抛中文错误——那是真的写不进去，
 *   继续放行只会让界面显示「已保存」而磁盘静默丢数据。
 */
import { isStorageUsable, readDesktopBridge, waitForDesktop, type DesktopBridge } from './desktop'
import { excerptOf, fallbackTitle, isIsoString, newId, normalizeTags } from './format'
import {
  CATEGORY_MAX_LENGTH,
  CONTENT_MAX_LENGTH,
  DEFAULT_CATEGORIES,
  TITLE_MAX_LENGTH,
  emptyNoteData,
  type CategoryCount,
  type Note,
  type NoteData,
  type NoteView,
} from './types'

/** 宿主 storage 的 key，落盘为 <pluginId>/note.json。 */
const REMOTE_KEY = 'note'
/** 浏览器模式下的 localStorage key。 */
const LOCAL_KEY = 'note:data'
/** 宿主 plugin-data 单值上限（与 apps/desktop/README.md 的 256 KiB 保持一致）。 */
const PLUGIN_DATA_MAX_BYTES = 256 * 1024
const DEFAULT_LIST_LIMIT = 20
const MAX_LIST_LIMIT = 200

/** 数据落点：宿主文件 or 浏览器本地。 */
export type StorageMode = 'desktop' | 'local'

type HostListener = (bridge: DesktopBridge) => void | Promise<void>

/** 列表查询条件，字段含义与 note_list_notes 工具一致。 */
export interface NoteQuery {
  query?: string
  category?: string
  limit?: number
  /** 为 true 时连同废纸篓里的笔记一起返回；默认只看正常笔记。 */
  include_deleted?: boolean
}

/** 列表查询结果；total 是未受 limit 限制的匹配总数。 */
export interface NoteListResult {
  items: NoteView[]
  total: number
}

/** 新建笔记入参；title 省略时用正文首句生成，category 缺省「思考」。 */
export interface CreateNoteInput {
  title?: string
  content: string
  category?: string
  tags?: string[]
}

/** 修改笔记入参：只有显式传入的字段会被改写。 */
export interface UpdateNoteInput {
  id: string
  title?: string
  content?: string
  category?: string
  tags?: string[]
}

let data: NoteData = emptyNoteData()
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
      console.error('[note] 订阅回调异常', error)
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
export function getData(): NoteData {
  return data
}

/** 当前持久化模式，用于界面状态行。 */
export function getStorageMode(): StorageMode {
  return mode
}

/** 当前宿主桥（未注入时为 null）。 */
export function getDesktopBridge(): DesktopBridge | null {
  return bridge
}

/** 登记「宿主就绪」回调；若桥已存在会立即回调一次（工具注册依赖这个时机）。 */
export function onHostAttach(listener: HostListener): void {
  if (hostListeners.has(listener)) return
  hostListeners.add(listener)
  const current = bridge ?? readDesktopBridge()
  if (current) void listener(current)
}

function cloneData(source: NoteData): NoteData {
  return JSON.parse(JSON.stringify(source)) as NoteData
}

/** 返回给调用方的笔记副本，避免外部直接改到内存快照里的对象。 */
function cloneNote(note: Note): Note {
  return { ...note, tags: [...note.tags] }
}

function readLocal(): NoteData | null {
  try {
    const raw = window.localStorage.getItem(LOCAL_KEY)
    if (!raw) return null
    return normalizeNoteData(JSON.parse(raw) as unknown)
  } catch (error) {
    console.warn('[note] 读取浏览器本地数据失败', error)
    return null
  }
}

function writeLocal(next: NoteData): void {
  try {
    window.localStorage.setItem(LOCAL_KEY, JSON.stringify(next))
  } catch (error) {
    // 配额满或隐私模式禁写：内存里仍可用，但这里只能告警，不能让用户无法继续记录
    console.warn('[note] 写入浏览器本地数据失败', error)
  }
}

async function readRemote(source: DesktopBridge): Promise<NoteData | null> {
  if (!isStorageUsable(source)) return null
  try {
    return normalizeNoteData(await source.storage.get(REMOTE_KEY))
  } catch (error) {
    console.warn('[note] 读取宿主持久化数据失败', error)
    return null
  }
}

async function readPersisted(): Promise<NoteData | null> {
  if (isStorageUsable(bridge)) return readRemote(bridge)
  return readLocal()
}

/** 统计 UTF-8 字节数：宿主按字节算 256 KiB 上限，中文一字三字节不能按字符数糊弄。 */
function byteLength(text: string): number {
  if (typeof TextEncoder === 'function') return new TextEncoder().encode(text).length
  // 极端兜底（无 TextEncoder 的旧环境）：按 UTF-16 双字节估算，只会更保守
  return text.length * 2
}

/** 写入前的体积闸门：超过宿主单值上限时抛中文错误，由界面/工具透出。 */
function assertWritable(next: NoteData): void {
  const bytes = byteLength(JSON.stringify(next))
  if (bytes <= PLUGIN_DATA_MAX_BYTES) return
  throw new Error(
    `笔记数据已超过宿主单值上限 256 KiB（当前约 ${Math.ceil(bytes / 1024)} KiB），请先删除或精简部分笔记`,
  )
}

async function persist(next: NoteData): Promise<void> {
  assertWritable(next)
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
async function mutate<T>(mutator: (draft: NoteData) => T): Promise<T> {
  return enqueue(async () => {
    const latest = await readPersisted()
    const draft = cloneData(latest ?? data)
    const result = mutator(draft)
    draft.updated_at = new Date().toISOString()
    // 先落盘再替换内存：写失败（含超限）时界面数据保持原样，不会出现「假保存」
    await persist(draft)
    data = draft
    emit()
    return result
  })
}

/** 分类名收敛：去空白、压空格、限长；空串返回 null 表示无效。 */
function normalizeCategoryName(raw: unknown): string | null {
  if (typeof raw !== 'string') return null
  const name = raw.trim().replace(/\s+/g, ' ')
  if (!name) return null
  return name.slice(0, CATEGORY_MAX_LENGTH)
}

function ensureCategory(list: string[], name: string): void {
  if (!list.includes(name)) list.push(name)
}

/**
 * 单条笔记收敛：非法/缺字段容错；content 字段缺失或非字符串视为损坏记录直接丢弃。
 *
 * 注意 content 为空字符串是合法状态：界面「新建笔记」会先落一条空正文草稿再让用户输入。
 * 这类草稿若从未编辑过，会在下次启动时由 pruneBlankDrafts 清掉；能编辑的草稿不能在这里丢，
 * 否则用户从「新建」到第一次输入之间的自动保存会读不到这条笔记（报「笔记不存在」）。
 */
function toNote(raw: unknown): Note | null {
  if (typeof raw !== 'object' || raw === null) return null
  const record = raw as Record<string, unknown>
  if (typeof record.content !== 'string') return null
  const content = record.content.slice(0, CONTENT_MAX_LENGTH)
  const createdAt = isIsoString(record.created_at) ? record.created_at : new Date().toISOString()
  const updatedAt = isIsoString(record.updated_at) ? record.updated_at : createdAt
  const rawTitle = typeof record.title === 'string' ? record.title : ''
  return {
    id: typeof record.id === 'string' && record.id.trim() ? record.id.trim() : newId(),
    // 空标题按正文首句回退，保证列表里永远有可读标题
    title: rawTitle.trim() ? rawTitle.trim().slice(0, TITLE_MAX_LENGTH) : fallbackTitle('', content),
    content,
    category: normalizeCategoryName(record.category) ?? DEFAULT_CATEGORIES[0],
    tags: normalizeTags(record.tags),
    created_at: createdAt,
    updated_at: updatedAt,
    // 软删时间只接受合法 ISO，其它值一律视为未删除
    deleted_at: isIsoString(record.deleted_at) ? record.deleted_at : null,
  }
}

/** 分类表收敛：内置分类恒在前，其余来自持久化分类表与笔记实际使用过的分类。 */
function normalizeCategories(raw: unknown, notes: Note[]): string[] {
  const result: string[] = [...DEFAULT_CATEGORIES]
  const push = (value: unknown): void => {
    const name = normalizeCategoryName(value)
    if (name) ensureCategory(result, name)
  }
  if (Array.isArray(raw)) raw.forEach(push)
  // 笔记引用了未登记的分类时补登记，避免界面上出现「分类列表里没有」的孤儿笔记
  notes.forEach((note) => ensureCategory(result, note.category))
  return result
}

/** 把任意来源的数据收敛成合法快照；非对象返回 null 表示「没有数据」。 */
function normalizeNoteData(raw: unknown): NoteData | null {
  if (typeof raw !== 'object' || raw === null) return null
  const record = raw as Record<string, unknown>
  const notes: Note[] = []
  const seen = new Set<string>()
  if (Array.isArray(record.notes)) {
    for (const item of record.notes) {
      const note = toNote(item)
      // id 重复会让「按 id 更新」落到错误对象上，保留先出现的一条
      if (!note || seen.has(note.id)) continue
      seen.add(note.id)
      notes.push(note)
    }
  }
  return {
    version: 1,
    categories: normalizeCategories(record.categories, notes),
    notes,
    updated_at: isIsoString(record.updated_at) ? record.updated_at : new Date().toISOString(),
  }
}

/** 从未被编辑过的空草稿：新建后直接关掉留下的「无标题笔记」，没必要一直占列表位。 */
function isBlankDraft(note: Note): boolean {
  const pristineTitle = note.title === '' || note.title === '无标题笔记'
  return !note.content.trim() && note.tags.length === 0 && pristineTitle
}

/** 启动时清理空草稿；返回原对象表示没有可清理内容（调用方据此决定是否写回）。 */
function pruneBlankDrafts(source: NoteData): NoteData {
  if (!source.notes.some(isBlankDraft)) return source
  return { ...source, notes: source.notes.filter((note) => !isBlankDraft(note)) }
}

async function notifyHost(detected: DesktopBridge): Promise<void> {
  for (const listener of hostListeners) {
    try {
      await listener(detected)
    } catch (error) {
      console.warn('[note] 宿主能力注册失败', error)
    }
  }
}

/** 远端快照是否「空」：没有笔记就算空，分类表里的自定义分类不构成用户数据。 */
function isRemoteEmpty(remote: NoteData | null): boolean {
  return remote === null || remote.notes.length === 0
}

/** 宿主就绪后接管数据：优先用宿主快照；远端为空且本地有数据时迁移一次。 */
async function attachHost(detected: DesktopBridge): Promise<void> {
  if (bridge === detected) return
  bridge = detected

  if (!isStorageUsable(detected)) {
    console.warn('[note] 宿主未提供 storage 能力，继续使用浏览器本地存储')
    emit()
    await notifyHost(detected)
    return
  }

  const remote = await readRemote(detected)
  mode = 'desktop'
  if (remote && !isRemoteEmpty(remote)) {
    const pruned = pruneBlankDrafts(remote)
    data = pruned
    // 上次会话遗留的空草稿顺手清出宿主文件，失败不影响本次使用
    if (pruned !== remote) {
      try {
        await persist(pruned)
      } catch (error) {
        console.warn('[note] 清理空草稿后写回宿主失败', error)
      }
    }
  } else {
    const local = readLocal()
    const migrating = local ? pruneBlankDrafts(local) : null
    if (migrating && migrating.notes.length > 0) {
      // 宿主首次使用：浏览器里已有的笔记不能丢，整体迁移过去。
      // 只迁一次的语义由「迁移后远端不再为空」自然保证，本地副本保留作为回退快照。
      data = migrating
      try {
        await persist(migrating)
        console.info('[note] 已将浏览器本地数据迁移到宿主持久化')
      } catch (error) {
        console.warn('[note] 迁移浏览器本地数据到宿主失败', error)
      }
    } else {
      data = remote ?? emptyNoteData()
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
  if (local) {
    const pruned = pruneBlankDrafts(local)
    data = pruned
    // 上次会话「新建后没写任何内容」的空草稿在这里清掉，并写回本地，避免每次启动都清一遍
    if (pruned !== local) writeLocal(pruned)
  }
  emit()

  window.addEventListener('desktop-ready', handleDesktopReady)
  const detected = await waitForDesktop()
  if (detected) await attachHost(detected)
}

/** 启动仓库：加载本地数据并尝试接入宿主；重复调用返回同一个 Promise。 */
export function initializeNote(): Promise<void> {
  if (!initPromise) initPromise = bootstrap()
  return initPromise
}

function compareUpdatedDesc(a: Note, b: Note): number {
  if (a.updated_at !== b.updated_at) return a.updated_at < b.updated_at ? 1 : -1
  if (a.created_at !== b.created_at) return a.created_at < b.created_at ? 1 : -1
  return 0
}

function toView(note: Note): NoteView {
  return {
    id: note.id,
    title: note.title,
    category: note.category,
    excerpt: excerptOf(note.content),
    tags: [...note.tags],
    created_at: note.created_at,
    updated_at: note.updated_at,
    deleted_at: note.deleted_at,
  }
}

/** 关键词匹配：标题/正文/标签，不区分大小写；正文按原始 Markdown 文本匹配，代码片段也能搜到。 */
function matchKeyword(note: Note, keyword: string): boolean {
  if (note.title.toLowerCase().includes(keyword)) return true
  if (note.content.toLowerCase().includes(keyword)) return true
  return note.tags.some((tag) => tag.toLowerCase().includes(keyword))
}

/** 按条件浏览笔记：更新时间倒序；默认只含正常笔记，total 为未受 limit 限制的总数。 */
export function listNotes(query: NoteQuery = {}): NoteListResult {
  const keyword = (query.query ?? '').trim().toLowerCase()
  const category = (query.category ?? '').trim()
  const rawLimit = Math.trunc(query.limit ?? DEFAULT_LIST_LIMIT)
  const limit = Math.min(
    Math.max(Number.isFinite(rawLimit) && rawLimit > 0 ? rawLimit : DEFAULT_LIST_LIMIT, 1),
    MAX_LIST_LIMIT,
  )

  const matched = data.notes.filter((note) => {
    if (!query.include_deleted && note.deleted_at !== null) return false
    if (category && note.category !== category) return false
    if (keyword && !matchKeyword(note, keyword)) return false
    return true
  })

  const sorted = [...matched].sort(compareUpdatedDesc)
  return { items: sorted.slice(0, limit).map(toView), total: matched.length }
}

/** 按 id 取完整笔记（含废纸篓里的）；返回副本。 */
export function getNote(id: string): Note | null {
  const note = data.notes.find((item) => item.id === id)
  return note ? cloneNote(note) : null
}

/** 分类及未删除笔记数量：内置分类按声明顺序在前，自定义分类按数量倒序在后。 */
export function listCategories(): CategoryCount[] {
  const counts = new Map<string, number>()
  for (const note of data.notes) {
    if (note.deleted_at !== null) continue
    counts.set(note.category, (counts.get(note.category) ?? 0) + 1)
  }

  const builtin = DEFAULT_CATEGORIES.map((name) => ({ name, count: counts.get(name) ?? 0 }))

  // 自定义分类 = 持久化分类表 ∪ 笔记实际使用的分类；同一分类只出现一次
  const seen = new Set<string>(DEFAULT_CATEGORIES)
  const custom: CategoryCount[] = []
  const pushCustom = (name: string): void => {
    if (seen.has(name)) return
    seen.add(name)
    custom.push({ name, count: counts.get(name) ?? 0 })
  }
  data.categories.forEach(pushCustom)
  counts.forEach((_, name) => pushCustom(name))

  // Array.prototype.sort 稳定，数量相同时保留登记顺序
  custom.sort((a, b) => b.count - a.count)
  return [...builtin, ...custom]
}

/** 废纸篓：只含软删笔记，按删除时间倒序。 */
export function trashNotes(): NoteView[] {
  return data.notes
    .filter((note) => note.deleted_at !== null)
    .sort((a, b) => ((a.deleted_at ?? '') < (b.deleted_at ?? '') ? 1 : -1))
    .map(toView)
}

function nowIso(): string {
  return new Date().toISOString()
}

/**
 * 新增笔记：空标题自动生成，未知分类自动登记。
 *
 * 正文不做非空校验：界面「新建笔记」是「先建空草稿再让用户输入」，AI 工具侧的必填校验
 * 留在 tools.ts（note_create_note 会先抛「缺少正文内容」）。空草稿在下次启动时被 pruneBlankDrafts 清掉。
 */
export async function createNote(input: CreateNoteInput): Promise<Note> {
  const content = (input.content ?? '').slice(0, CONTENT_MAX_LENGTH)
  const category = normalizeCategoryName(input.category) ?? DEFAULT_CATEGORIES[0]
  const note: Note = {
    id: newId(),
    title: fallbackTitle(input.title ?? '', content).slice(0, TITLE_MAX_LENGTH),
    content,
    category,
    tags: normalizeTags(input.tags),
    created_at: nowIso(),
    updated_at: nowIso(),
    deleted_at: null,
  }

  return mutate((draft) => {
    draft.notes.push(note)
    ensureCategory(draft.categories, category)
    return cloneNote(note)
  })
}

/**
 * 修改笔记：只改显式传入的字段。
 *
 * 允许把正文改成空串（textarea 清空后再重写、以及删除段落期间的自动保存都会经过这里），
 * 否则每次清空都会 rejects 并让界面一直停在「保存失败」。AI 工具的必填校验在 tools.ts。
 */
export async function updateNote(input: UpdateNoteInput): Promise<Note> {
  const nextContent = input.content

  return mutate((draft) => {
    const note = draft.notes.find((item) => item.id === input.id)
    if (!note) throw new Error('笔记不存在')

    if (nextContent !== undefined) note.content = nextContent.slice(0, CONTENT_MAX_LENGTH)
    if (input.title !== undefined) {
      note.title = fallbackTitle(input.title, note.content).slice(0, TITLE_MAX_LENGTH)
    }
    if (input.tags !== undefined) note.tags = normalizeTags(input.tags)
    if (input.category !== undefined) {
      const category = normalizeCategoryName(input.category)
      if (category) {
        note.category = category
        ensureCategory(draft.categories, category)
      }
    }
    note.updated_at = nowIso()
    return cloneNote(note)
  })
}

/** 归类到指定分类；分类不存在时自动登记。 */
export async function setCategory(id: string, category: string): Promise<Note> {
  const name = normalizeCategoryName(category)
  if (!name) throw new Error('分类名称不能为空')

  return mutate((draft) => {
    const note = draft.notes.find((item) => item.id === id)
    if (!note) throw new Error('笔记不存在')
    note.category = name
    note.updated_at = nowIso()
    ensureCategory(draft.categories, name)
    return cloneNote(note)
  })
}

/** 新增自定义分类（重复则去重），返回最新分类表。 */
export async function addCategory(name: string): Promise<string[]> {
  const normalized = normalizeCategoryName(name)
  if (!normalized) throw new Error('请输入分类名称')

  return mutate((draft) => {
    ensureCategory(draft.categories, normalized)
    return [...draft.categories]
  })
}

/** 软删除：只写 deleted_at，数据仍在 JSON 里，可在界面恢复。 */
export async function deleteNote(id: string): Promise<Note> {
  return mutate((draft) => {
    const note = draft.notes.find((item) => item.id === id)
    if (!note) throw new Error('笔记不存在')
    if (note.deleted_at === null) {
      note.deleted_at = nowIso()
      note.updated_at = note.deleted_at
    }
    return cloneNote(note)
  })
}

/** 从废纸篓恢复。 */
export async function restoreNote(id: string): Promise<Note> {
  return mutate((draft) => {
    const note = draft.notes.find((item) => item.id === id)
    if (!note) throw new Error('笔记不存在')
    note.deleted_at = null
    note.updated_at = nowIso()
    return cloneNote(note)
  })
}

/** 物理删除（仅用于废纸篓里的「彻底删除」），不可恢复。 */
export async function purgeNote(id: string): Promise<void> {
  return mutate((draft) => {
    const index = draft.notes.findIndex((item) => item.id === id)
    if (index < 0) throw new Error('笔记不存在')
    draft.notes.splice(index, 1)
  })
}
