/**
 * 纯格式化/解析工具：不依赖宿主与 React，方便工具层与界面共用，也便于验证脚本直接跑。
 */
import { TAG_MAX_COUNT, TAG_MAX_LENGTH } from './types'

/** 生成笔记 id：优先 crypto.randomUUID，旧环境退化为时间戳 + 随机串。 */
export function newId(): string {
  const cryptoApi = globalThis.crypto
  if (cryptoApi && typeof cryptoApi.randomUUID === 'function') return cryptoApi.randomUUID()
  return `note-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

/** 判断是否为可用作时间戳的 ISO 字符串。 */
export function isIsoString(value: unknown): value is string {
  if (typeof value !== 'string' || !value) return false
  const time = Date.parse(value)
  return Number.isFinite(time)
}

/** 去掉 Markdown 记号，压成单行纯文本，供列表摘要与 AI 关键词搜索使用。 */
export function plainText(content: string): string {
  return content
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/!\[[^\]]*]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)]\([^)]*\)/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^\s*>\s?/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/^\s*\d+\.\s+/gm, '')
    .replace(/[*_~`]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

/** 正文摘要：默认 80 字，超出补省略号。 */
export function excerptOf(content: string, maxLength = 80): string {
  const text = plainText(content)
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength)}…`
}

function startOfDay(time: number): number {
  const date = new Date(time)
  date.setHours(0, 0, 0, 0)
  return date.getTime()
}

function pad(value: number): string {
  return value < 10 ? `0${value}` : String(value)
}

/** 列表里的相对日期：今天 14:32 / 昨天 / 4月18日 / 2025年4月18日。 */
export function formatNoteDate(iso: string, now = Date.now()): string {
  const time = Date.parse(iso)
  if (!Number.isFinite(time)) return ''
  const date = new Date(time)
  const days = Math.round((startOfDay(now) - startOfDay(time)) / 86_400_000)
  if (days === 0) return `今天 ${pad(date.getHours())}:${pad(date.getMinutes())}`
  if (days === 1) return '昨天'
  if (date.getFullYear() === new Date(now).getFullYear()) {
    return `${date.getMonth() + 1}月${date.getDate()}日`
  }
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`
}

/** 编辑器信息行：2026年10月25日。 */
export function formatLongDate(iso: string): string {
  const time = Date.parse(iso)
  if (!Number.isFinite(time)) return ''
  const date = new Date(time)
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`
}

/** 标签收敛：去空、去重、限长限数量；任何来源（界面/模型）都经过这里。 */
export function normalizeTags(raw: unknown): string[] {
  if (!Array.isArray(raw)) return []
  const result: string[] = []
  for (const item of raw) {
    if (typeof item !== 'string') continue
    const tag = item.trim().replace(/^#/, '').replace(/\s+/g, ' ')
    if (!tag) continue
    const trimmed = tag.slice(0, TAG_MAX_LENGTH)
    if (!result.includes(trimmed)) result.push(trimmed)
    if (result.length >= TAG_MAX_COUNT) break
  }
  return result
}

/** 标题回退：空标题用正文首行，再退回「无标题笔记」。 */
export function fallbackTitle(title: string, content: string): string {
  const trimmed = title.trim()
  if (trimmed) return trimmed
  const firstLine = plainText(content).split('。')[0]?.trim() ?? ''
  return firstLine ? firstLine.slice(0, 24) : '无标题笔记'
}
