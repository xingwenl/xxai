import { describe, expect, it } from 'vitest'
import { contextRingState, formatTokens } from '../context-ring'

describe('contextRingState', () => {
  it('环旁只给百分比，绝对量放在 detail 里供悬停提示', () => {
    expect(contextRingState(12300, 1_000_000)).toMatchObject({
      text: '1%',
      detail: '12.3K / 1.0M'
    })
    expect(contextRingState(12300, 1_000_000)?.ratio).toBeCloseTo(1.23)
    expect(contextRingState(12300, 1_000_000)?.color).toContain('--agent-primary')
  })

  it('接近上限时给整数百分比', () => {
    expect(contextRingState(950_000, 1_000_000)).toMatchObject({
      text: '95%',
      detail: '950.0K / 1.0M'
    })
  })

  it('恰好 70% 进入警告色，恰好 90% 进入危险色', () => {
    expect(contextRingState(70, 100)?.ratio).toBe(70)
    expect(contextRingState(70, 100)?.color).toBe('#F59E0B')
    expect(contextRingState(69.9, 100)?.color).toContain('--agent-primary')
    expect(contextRingState(90, 100)?.color).toBe('#EF4444')
    expect(contextRingState(89.9, 100)?.color).toBe('#F59E0B')
  })

  it('占用超过窗口时 ratio 截断到 100，detail 仍显示真实用量', () => {
    expect(contextRingState(1_200_000, 1_000_000)).toMatchObject({
      ratio: 100,
      color: '#EF4444',
      text: '100%',
      detail: '1.2M / 1.0M'
    })
  })

  it('窗口未知或非法时返回 null（调用方降级为只显示绝对 token 数）', () => {
    expect(contextRingState(12300, undefined)).toBeNull()
    expect(contextRingState(12300, null)).toBeNull()
    expect(contextRingState(12300, 0)).toBeNull()
    expect(contextRingState(12300, -1)).toBeNull()
    expect(contextRingState(12300, Number.NaN)).toBeNull()
    expect(contextRingState(12300, Number.POSITIVE_INFINITY)).toBeNull()
  })

  it('用量非法时返回 null', () => {
    expect(contextRingState(undefined, 100)).toBeNull()
    expect(contextRingState(null, 100)).toBeNull()
    expect(contextRingState(-1, 100)).toBeNull()
    expect(contextRingState(Number.NaN, 100)).toBeNull()
    expect(contextRingState(Number.POSITIVE_INFINITY, 100)).toBeNull()
  })

  it('占用为 0 时是 0%，而不是空环或 <1%', () => {
    expect(contextRingState(0, 1_000_000)).toMatchObject({
      ratio: 0,
      text: '0%',
      detail: '0 / 1.0M'
    })
  })

  it('有占用但四舍五入成 0% 时说成 <1%，避免看起来像没读到数据', () => {
    // 1000 / 1,000,000 = 0.1%，四舍五入是 0。
    expect(contextRingState(1_000, 1_000_000)?.text).toBe('<1%')
  })
})

describe('formatTokens', () => {
  it('1000 进位，保留一位小数', () => {
    expect(formatTokens(999)).toBe('999')
    expect(formatTokens(1200)).toBe('1.2K')
    expect(formatTokens(1_000_000)).toBe('1.0M')
    expect(formatTokens(12_345)).toBe('12.3K')
  })

  it('非法输入退化为 0', () => {
    expect(formatTokens(Number.NaN)).toBe('0')
    expect(formatTokens(-1)).toBe('0')
  })
})
