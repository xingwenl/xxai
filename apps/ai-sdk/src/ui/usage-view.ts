/**
 * 用量 chip 与明细卡的展示文案。
 *
 * 排版对齐 DSH 的「本轮用量」弹层：chip 只给一个紧凑总量（`用量 1.3M tok`），
 * 点开后是「本轮用量 + 总量」标题行与五行明细（提供方/模型、缓存命中率、
 * 未缓存输入、缓存读取、输出）。缺哪一项就整行不渲染——不显示假的 0。
 */
import type { ModelUsage } from '../core/usage'
import { cacheHitPercent, uncachedPromptTokens } from '../core/usage'
import { formatTokens } from './context-ring'

export interface UsageDetailRow {
  label: string
  value: string
}

export interface UsageChipView {
  /** chip 文案，形如 `用量 1.3M tok`。 */
  text: string
  /** 明细卡标题：`本轮用量`。 */
  title: string
  /** 标题右侧的精确总量，形如 `1,332,145 tok`。 */
  totalText: string
  rows: UsageDetailRow[]
}

/** 会话累计行的文案：`本会话累计 1.3M tok · 缓存命中 94%`。 */
export interface SessionUsageView {
  text: string
  /** 悬停提示用的精确值，形如 `本会话累计 1,332,145 tok`。 */
  detail: string
}

const CHIP_TITLE = '本轮用量'

function formatCount(value: number): string {
  return Math.round(value).toLocaleString('en-US')
}

function tokenText(value: number): string {
  return `${formatCount(value)} tok`
}

/** 单条 assistant 消息 → chip 与明细卡文案；没有可用用量时返回 `null`。 */
export function usageChipView(
  usage: ModelUsage | null | undefined,
): UsageChipView | null {
  if (!usage) return null
  const rows: UsageDetailRow[] = []
  const modelLine =
    usage.provider && usage.model
      ? `${usage.provider} / ${usage.model}`
      : usage.model || usage.provider
  if (modelLine) {
    rows.push({ label: '提供方/模型', value: modelLine })
  }
  const hitPercent = cacheHitPercent(usage)
  if (hitPercent !== null) {
    rows.push({ label: '缓存命中', value: `${hitPercent}%` })
  }
  const uncached = uncachedPromptTokens(usage)
  if (uncached !== null) {
    rows.push({ label: '未缓存输入', value: tokenText(uncached) })
  }
  if (usage.cacheReadTokens !== undefined) {
    rows.push({ label: '缓存读取', value: tokenText(usage.cacheReadTokens) })
  }
  rows.push({ label: '输出', value: tokenText(usage.completionTokens) })
  return {
    text: `用量 ${formatTokens(usage.totalTokens)} tok`,
    title: CHIP_TITLE,
    totalText: tokenText(usage.totalTokens),
    rows,
  }
}

/** 会话累计行文案；没有任何可用用量时返回 `null`。 */
export function sessionUsageView(
  usage: ModelUsage | null | undefined,
): SessionUsageView | null {
  if (!usage) return null
  const hitPercent = cacheHitPercent(usage)
  const parts = [`本会话累计 ${formatTokens(usage.totalTokens)} tok`]
  if (hitPercent !== null) {
    parts.push(`缓存命中 ${hitPercent}%`)
  }
  return {
    text: parts.join(' · '),
    detail: `本会话累计 ${tokenText(usage.totalTokens)}`,
  }
}
