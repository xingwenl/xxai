import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TWO_STEP_CONFIRM_TIMEOUT_MS, useTwoStepConfirm } from '../two-step-confirm'

describe('useTwoStepConfirm', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('首次点击只进入待确认态，不触发操作', () => {
    const confirmState = useTwoStepConfirm()

    expect(confirmState.confirm('42')).toBe(false)
    expect(confirmState.isPending('42')).toBe(true)
    // 其他目标不能被误认为已确认。
    expect(confirmState.isPending('43')).toBe(false)
  })

  it('对同一目标再点一次才返回 true 并立即复位', () => {
    const confirmState = useTwoStepConfirm()

    confirmState.confirm('42')
    expect(confirmState.confirm('42')).toBe(true)
    // 复位后第三次点击应重新要求确认，避免连续误删。
    expect(confirmState.isPending('42')).toBe(false)
    expect(confirmState.confirm('42')).toBe(false)
  })

  it('超时后自动取消待确认态', () => {
    const confirmState = useTwoStepConfirm()

    confirmState.confirm('42')
    vi.advanceTimersByTime(TWO_STEP_CONFIRM_TIMEOUT_MS - 1)
    expect(confirmState.isPending('42')).toBe(true)

    vi.advanceTimersByTime(1)
    expect(confirmState.isPending('42')).toBe(false)
    // 超时后同一目标再点仍是「第一次点击」。
    expect(confirmState.confirm('42')).toBe(false)
  })

  it('切换到另一个目标时重置上一个目标', () => {
    const confirmState = useTwoStepConfirm()

    confirmState.confirm('42')
    expect(confirmState.confirm('43')).toBe(false)
    expect(confirmState.isPending('42')).toBe(false)
    expect(confirmState.isPending('43')).toBe(true)

    // 上一个目标的定时器不应把当前目标一起清掉。
    vi.advanceTimersByTime(TWO_STEP_CONFIRM_TIMEOUT_MS - 1)
    expect(confirmState.isPending('43')).toBe(true)
  })

  it('数字与会话 ID 字符串视为同一个目标', () => {
    const confirmState = useTwoStepConfirm()

    expect(confirmState.confirm(42)).toBe(false)
    expect(confirmState.isPending('42')).toBe(true)
    // 模板里 item.id 是 number，父层状态可能是 String(id)，两者必须互通。
    expect(confirmState.confirm('42')).toBe(true)
  })

  it('cancel 可随时清空待确认态', () => {
    const confirmState = useTwoStepConfirm()

    confirmState.confirm('42')
    confirmState.cancel()
    expect(confirmState.pendingKey.value).toBeNull()
  })
})
