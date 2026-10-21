// 首页概览卡桥：把子应用推送的「标题 + 指标 + 最近条目」汇总到宿主首页。
//
// 与 tool-bridge 同形态：内存注册表 + 订阅通知，不落盘。子应用在 desktop-ready
// 之后调用 desktop.dashboard.publish(...)，宿主重新挂载 iframe（热重载/开关插件）
// 后由子应用重新推送；因此卡片数据天然跟随子应用，不需要宿主做持久化。

import type { Plugin } from './api'

/** 概览卡里的一项指标：左侧标签 + 右侧数值。 */
export interface DashboardMetric {
  label: string
  value: string
}

/** 概览卡里的一条最近记录。 */
export interface DashboardRecentItem {
  text: string
  hint?: string
}

/** 子应用推送的概览卡；宿主只展示，不解释业务含义。 */
export interface DashboardCard {
  pluginId: string
  pluginName: string
  title: string
  metrics: DashboardMetric[]
  recent: DashboardRecentItem[]
  /** 没有任何数据时展示的文案（例如「本月还没有记账」） */
  emptyText: string
}

/**
 * 卡片字段上限：宿主统一截断，避免子应用推一个巨型 payload 把首页撑爆。
 * 数值超长时截断而不是报错，让子应用总能推出内容。
 */
const LIMITS = {
  title: 40,
  metrics: 4,
  metricLabel: 12,
  metricValue: 24,
  recent: 5,
  recentText: 80,
  recentHint: 24,
  emptyText: 40,
} as const

const cards = new Map<string, DashboardCard>()
const listeners = new Set<() => void>()

function notify(): void {
  for (const listener of listeners) {
    try {
      listener()
    } catch (err) {
      console.error('[dashboard-bridge] 监听器异常', err)
    }
  }
}

function clip(text: unknown, limit: number): string {
  if (typeof text !== 'string') return ''
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}

/**
 * 发布/更新概览卡；payload 结构非法（比如 metrics 不是数组）时返回 false。
 * 字段只做截断不做校验报错：卡片是展示层，子应用不该因为文案过长而报错。
 */
export function publishDashboardCard(plugin: Plugin, payload: unknown): boolean {
  const input = payload as Record<string, unknown> | null
  if (!input || typeof input !== 'object' || Array.isArray(input)) return false

  const rawMetrics = Array.isArray(input.metrics) ? input.metrics : []
  const rawRecent = Array.isArray(input.recent) ? input.recent : []
  const metrics: DashboardMetric[] = rawMetrics
    .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
    .slice(0, LIMITS.metrics)
    .map((item) => ({
      label: clip(item.label, LIMITS.metricLabel),
      value: clip(item.value, LIMITS.metricValue),
    }))
    .filter((item) => item.label || item.value)
  const recent: DashboardRecentItem[] = rawRecent
    .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
    .slice(0, LIMITS.recent)
    .map((item) => ({
      text: clip(item.text, LIMITS.recentText),
      hint: clip(item.hint, LIMITS.recentHint) || undefined,
    }))
    .filter((item) => item.text)

  cards.set(plugin.id, {
    pluginId: plugin.id,
    pluginName: plugin.name,
    title: clip(input.title, LIMITS.title) || plugin.name,
    metrics,
    recent,
    emptyText: clip(input.emptyText, LIMITS.emptyText),
  })
  notify()
  return true
}

/** 撤销概览卡（子应用卸载 / 用户主动 clear）；不存在的卡片直接忽略。 */
export function clearDashboardCard(pluginId: string): void {
  if (cards.delete(pluginId)) notify()
}

/** 当前所有概览卡（按推送顺序）。 */
export function getDashboardCards(): DashboardCard[] {
  return [...cards.values()]
}

/** 订阅卡片变化；返回取消订阅函数。 */
export function subscribeDashboardCards(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** 测试与热重载重挂载用：清空全部卡片（宿主页面重载时也会自然清空）。 */
export function clearAllDashboardCards(): void {
  if (cards.size === 0) return
  cards.clear()
  notify()
}
