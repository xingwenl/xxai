/**
 * 向桌面全局助手暴露的 note_* 方法。
 *
 * 契约：名称/描述/inputSchema/sideEffect 的唯一来源是 `apps/note/tools.json`
 * （宿主侧后台策略按同一份 schema 生成指纹），这里只负责把模型给的入参
 * 按 unknown 收敛、调用仓库、再拼回对模型友好的字段；非法入参抛中文错误。
 */
import type { DesktopBridge, DesktopToolDef, DesktopToolHandler } from './desktop'
import { normalizeTags } from './format'
import {
  createNote,
  deleteNote,
  getNote,
  listCategories,
  listNotes,
  onHostAttach,
  setCategory,
  updateNote,
  type NoteQuery,
  type UpdateNoteInput,
} from './store'
import type { Note } from './types'
import toolsSchema from '../../tools.json'

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {}
}

function readString(source: Record<string, unknown>, key: string): string | undefined {
  const value = source[key]
  return typeof value === 'string' ? value : undefined
}

/** 数字入参宽松解析：兼容模型把 limit 写成字符串的情况。 */
function readNumber(source: Record<string, unknown>, key: string): number | undefined {
  const value = source[key]
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return undefined
}

/** 标签：只有数组才认，其它类型按「没传」处理（模型常把 tags 写成逗号串）。 */
function readTags(source: Record<string, unknown>): string[] | undefined {
  const value = source.tags
  return Array.isArray(value) ? normalizeTags(value) : undefined
}

/** id 缺失/非字符串时统一按「笔记不存在」报，避免把内部 id 校验细节暴露给模型。 */
function requireId(source: Record<string, unknown>): string {
  const id = (readString(source, 'id') ?? '').trim()
  if (!id) throw new Error('笔记不存在')
  return id
}

/** 工具里的 note 返回结构：列表场景不带正文，单条场景才带 content。 */
function toNotePayload(note: Note, includeContent: boolean): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    id: note.id,
    title: note.title,
    category: note.category,
    tags: [...note.tags],
    created_at: note.created_at,
    updated_at: note.updated_at,
  }
  if (includeContent) payload.content = note.content
  return payload
}

/** 新建笔记：content 必填；title 省略时由仓库按正文首句生成。 */
async function handleCreateNote(args: unknown): Promise<unknown> {
  const input = asRecord(args)
  const content = readString(input, 'content')
  if (content === undefined || !content.trim()) throw new Error('缺少正文内容')

  const note = await createNote({
    content,
    title: readString(input, 'title'),
    category: readString(input, 'category'),
    tags: readTags(input),
  })

  return {
    ok: true,
    note: toNotePayload(note, true),
    // 只回分类名：模型下一步归类时直接可用，不必再从对象里取值
    categories: listCategories().map((item) => item.name),
  }
}

/** 浏览笔记：关键词搜标题/正文/标签，分类精确匹配，limit 缺省 20、最大 200。 */
async function handleListNotes(args: unknown): Promise<unknown> {
  const input = asRecord(args)
  const query: NoteQuery = {
    query: readString(input, 'query'),
    category: readString(input, 'category'),
    limit: readNumber(input, 'limit'),
  }
  const result = listNotes(query)

  return {
    items: result.items.map((item) => ({
      id: item.id,
      title: item.title,
      category: item.category,
      excerpt: item.excerpt,
      tags: item.tags,
      created_at: item.created_at,
      updated_at: item.updated_at,
    })),
    total: result.total,
  }
}

/** 读取单条笔记全文；不存在时抛「笔记不存在」。 */
async function handleGetNote(args: unknown): Promise<unknown> {
  const input = asRecord(args)
  const note = getNote(requireId(input))
  if (!note) throw new Error('笔记不存在')
  return { note: toNotePayload(note, true) }
}

/** 修改笔记：只把显式传入的字段交给仓库，未传字段保持原值。 */
async function handleUpdateNote(args: unknown): Promise<unknown> {
  const input = asRecord(args)
  const id = requireId(input)

  const patch: UpdateNoteInput = { id }
  const title = readString(input, 'title')
  if (title !== undefined) patch.title = title
  const content = readString(input, 'content')
  if (content !== undefined) {
    if (!content.trim()) throw new Error('缺少正文内容')
    patch.content = content
  }
  const category = readString(input, 'category')
  if (category !== undefined && category.trim()) patch.category = category
  const tags = readTags(input)
  if (tags !== undefined) patch.tags = tags

  const note = await updateNote(patch)
  return { ok: true, note: toNotePayload(note, true) }
}

/** 归类：分类名必填，不存在时仓库会自动登记。 */
async function handleSetCategory(args: unknown): Promise<unknown> {
  const input = asRecord(args)
  const id = requireId(input)
  const category = (readString(input, 'category') ?? '').trim()
  if (!category) throw new Error('分类名称不能为空')

  const note = await setCategory(id, category)
  return {
    ok: true,
    note: toNotePayload(note, true),
    categories: listCategories().map((item) => item.name),
  }
}

/** 列出分类与未删除笔记数量（内置分类恒在，自定义分类按数量倒序）。 */
async function handleListCategories(): Promise<unknown> {
  const categories = listCategories()
  return { categories, total: categories.length }
}

/** 软删除到废纸篓：数据仍在，界面可恢复。 */
async function handleDeleteNote(args: unknown): Promise<unknown> {
  const input = asRecord(args)
  const note = await deleteNote(requireId(input))
  return { ok: true, id: note.id, deleted_at: note.deleted_at }
}

const TOOL_DEFS = toolsSchema as DesktopToolDef[]

const TOOL_NAMES = TOOL_DEFS.map((tool) => tool.name)

const HANDLERS: Record<string, DesktopToolHandler> = {
  note_create_note: handleCreateNote,
  note_list_notes: handleListNotes,
  note_get_note: handleGetNote,
  note_update_note: handleUpdateNote,
  note_set_category: handleSetCategory,
  note_list_categories: handleListCategories,
  note_delete_note: handleDeleteNote,
}

let installed = false
let registeredBridge: DesktopBridge | null = null

/**
 * 注册 note_* 工具：宿主未提供 tools 能力或注册失败时只告警，不影响页面记笔记。
 * 必须在 initializeNote 之前调用，保证宿主就绪时监听已经就位。
 */
export function installNoteTools(): void {
  if (installed) return
  installed = true
  onHostAttach(async (bridge) => {
    if (registeredBridge === bridge) return
    registeredBridge = bridge
    if (!bridge.tools || typeof bridge.tools.register !== 'function') {
      console.warn('[note] 宿主未提供 tools 能力，跳过工具注册')
      return
    }
    try {
      await bridge.tools.register(TOOL_DEFS, HANDLERS)
    } catch (error) {
      console.warn('[note] 注册笔记工具失败', error)
    }
  })
}

/** 注销本子应用的工具（页面卸载或热更新时可用）。 */
export async function uninstallNoteTools(bridge: DesktopBridge | null): Promise<void> {
  if (!bridge?.tools || typeof bridge.tools.unregister !== 'function') return
  try {
    await bridge.tools.unregister(TOOL_NAMES)
  } catch (error) {
    console.warn('[note] 注销笔记工具失败', error)
  }
}
