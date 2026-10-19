/**
 * 上下文占用环的展示状态计算。
 *
 * 与 `quota-ring.ts` 的差别仅在口径：配额环的 `ratio` 是 0–1（且以 1 为
 * 耗尽线），而上下文占用是「用了多少 / 模型窗口多大」，业务上按百分比表述
 * （<70% 正常、70–90% 偏高、≥90% 接近溢出），因此这里的 `ratio` 是 0–100。
 * 消费方驱动 SVG 弧长时记得除以 100。
 */

export interface ContextRingState {
  /** 占用百分比，取值 0–100（超出窗口时截断到 100）。 */
  ratio: number
  color: string
  text: string
}

const NORMAL_COLOR = 'var(--agent-primary, #0EA5E9)'
const WARNING_COLOR = '#F59E0B'
const DANGER_COLOR = '#EF4444'

/**
 * 把 token 数格式化成 `1.2K` / `1.0M` 这样的紧凑文本。
 *
 * 采用 1000 进位而非 1024：模型窗口与用量都是以 K/M 的十进制口径公布的
 * （128K、1M），用 1024 会让 1,000,000 显示成 976.6K，对不上用户的认知。
 */
export function formatTokens(value: number): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    return '0'
  }
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`
  }
  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(1)}K`
  }
  return String(Math.round(value))
}

/**
 * 计算上下文占用环的状态。
 *
 * 窗口大小缺失、非正数或非有限时返回 `null`：后端在拿不到模型窗口
 * （`source === 'estimated'` 且推算不出）时会上报 `windowTokens: null`，
 * 此时没有百分比可言，调用方应降级为只显示绝对 token 数而不是画一个
 * 分母错误的环。`usedTokens` 非法时同样返回 `null`。
 */
export function contextRingState(
  usedTokens: number | null | undefined,
  windowTokens: number | null | undefined
): ContextRingState | null {
  if (
    typeof windowTokens !== 'number' ||
    !Number.isFinite(windowTokens) ||
    windowTokens <= 0
  ) {
    return null
  }
  if (
    typeof usedTokens !== 'number' ||
    !Number.isFinite(usedTokens) ||
    usedTokens < 0
  ) {
    return null
  }
  const ratio = Math.min(100, (usedTokens / windowTokens) * 100)
  const color = ratio >= 90 ? DANGER_COLOR : ratio >= 70 ? WARNING_COLOR : NORMAL_COLOR
  return {
    ratio,
    color,
    text: `${formatTokens(usedTokens)}/${formatTokens(windowTokens)} (${Math.round(ratio)}%)`
  }
}
