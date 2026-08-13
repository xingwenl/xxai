import type { WindowRect } from './window-layout'

export const WINDOW_STORAGE_SUFFIX = ':window'

export function serializeWindowRect(rect: WindowRect): string {
  return JSON.stringify(rect)
}

export function parseWindowRect(raw: string | null): WindowRect | null {
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as Partial<WindowRect>
    const { x, y, width, height } = value
    const validNumber = (n: unknown): n is number =>
      typeof n === 'number' && Number.isFinite(n)
    if (
      validNumber(x) &&
      validNumber(y) &&
      validNumber(width) &&
      width > 0 &&
      validNumber(height) &&
      height > 0
    ) {
      return { x, y, width, height }
    }
  } catch {
    // 持久化数据损坏时忽略，回退到默认布局。
  }
  return null
}
