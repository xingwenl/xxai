import { describe, expect, it } from 'vitest'
import { quotaRingState } from '../quota-ring'

describe('quotaRingState', () => {
  it('正常用量返回主题色与已用/限额文本', () => {
    expect(quotaRingState(12, 60)).toMatchObject({
      ratio: 0.2,
      text: '12/60'
    })
    expect(quotaRingState(12, 60)?.color).toContain('--agent-primary')
  })

  it('用量达到 70% 以上切换为警告色', () => {
    expect(quotaRingState(45, 60)?.color).toBe('#F59E0B')
    expect(quotaRingState(42, 60)?.ratio).toBeCloseTo(0.7)
  })

  it('用量用尽或超过限额时显示红色并封顶', () => {
    expect(quotaRingState(60, 60)).toMatchObject({
      ratio: 1,
      color: '#EF4444',
      text: '60/60'
    })
    expect(quotaRingState(75, 60)).toMatchObject({
      ratio: 1,
      color: '#EF4444',
      text: '60/60'
    })
  })

  it('limit 缺失、为 0 或非法时返回 null（调用方不渲染）', () => {
    expect(quotaRingState(12, undefined)).toBeNull()
    expect(quotaRingState(12, 0)).toBeNull()
    expect(quotaRingState(12, -1)).toBeNull()
    expect(quotaRingState(Number.NaN, 60)).toBeNull()
    expect(quotaRingState(12, Number.POSITIVE_INFINITY)).toBeNull()
  })

  it('用量为 0 时返回空进度与 0/limit 文本', () => {
    expect(quotaRingState(0, 60)).toMatchObject({
      ratio: 0,
      text: '0/60'
    })
  })
})
