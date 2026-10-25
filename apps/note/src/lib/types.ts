/**
 * 笔记数据模型与共享常量。
 *
 * 字段命名一旦发布就会被「AI 工具返回结构 / 宿主持久化 JSON」同时引用，
 * 修改前先确认迁移策略（当前 version 固定为 1，读取时对缺字段做收敛）。
 */

/** 内置分类：用户不可删除，AI 归类时可直接使用。 */
export const DEFAULT_CATEGORIES = ['思考', '灵感', '阅读', '旅行', '工作'] as const

/** 软删后的笔记仍保留在 JSON 里，只是 deleted_at 非空。 */
export interface Note {
  id: string
  title: string
  /** 正文：纯文本 Markdown，不做 HTML 富文本。 */
  content: string
  category: string
  tags: string[]
  created_at: string
  updated_at: string
  /** 软删时间；null 表示正常笔记。 */
  deleted_at: string | null
}

/** 持久化快照：整份 JSON 存在宿主 plugin-data 的 `note` key 下。 */
export interface NoteData {
  version: 1
  categories: string[]
  notes: Note[]
  updated_at: string
}

/** 列表项视图：不含正文，只带摘要，避免把大段正文塞进工具返回值与列表渲染。 */
export interface NoteView {
  id: string
  title: string
  category: string
  excerpt: string
  tags: string[]
  created_at: string
  updated_at: string
  deleted_at: string | null
}

/** 分类及其笔记数量。 */
export interface CategoryCount {
  name: string
  count: number
}

export const CATEGORY_MAX_LENGTH = 20
export const TITLE_MAX_LENGTH = 120
export const CONTENT_MAX_LENGTH = 20000
export const TAG_MAX_LENGTH = 16
export const TAG_MAX_COUNT = 8

/** 空快照：内置分类始终存在。 */
export function emptyNoteData(): NoteData {
  return {
    version: 1,
    categories: [...DEFAULT_CATEGORIES],
    notes: [],
    updated_at: new Date().toISOString(),
  }
}
