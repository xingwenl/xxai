export interface QuotaRingState {
  ratio: number
  color: string
  text: string
}

const NORMAL_COLOR = 'var(--agent-primary, #0EA5E9)'
const WARNING_COLOR = '#F59E0B'
const EXHAUSTED_COLOR = '#EF4444'

/**
 * 计算圆形进度条的展示状态。
 *
 * ratio 用于驱动 SVG 圆弧长度；颜色按用量分三档（<70% 主题色、
 * 70-90% 橙色、>=100% 红色）；limit 缺失或非法时返回 null，调用方不渲染。
 */
export function quotaRingState(
  current: number | undefined,
  limit: number | undefined
): QuotaRingState | null {
  if (
    typeof limit !== 'number' ||
    !Number.isFinite(limit) ||
    limit <= 0 ||
    typeof current !== 'number' ||
    !Number.isFinite(current)
  ) {
    return null
  }
  const used = Math.max(0, Math.min(limit, current))
  const ratio = limit > 0 ? used / limit : 0
  const color =
    ratio >= 1 ? EXHAUSTED_COLOR : ratio >= 0.7 ? WARNING_COLOR : NORMAL_COLOR
  return {
    ratio,
    color,
    text: `${used}/${limit}`
  }
}
