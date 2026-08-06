import { describe, expect, it } from 'vitest'
import { isNearScrollBottom } from '../chat-scroll'

describe('isNearScrollBottom', () => {
  it('keeps following while the reader remains near the bottom', () => {
    expect(isNearScrollBottom({ scrollTop: 452, scrollHeight: 1000, clientHeight: 500 })).toBe(true)
    expect(isNearScrollBottom({ scrollTop: 451, scrollHeight: 1000, clientHeight: 500 })).toBe(false)
  })

  it('treats short message lists as already at the bottom', () => {
    expect(isNearScrollBottom({ scrollTop: 0, scrollHeight: 320, clientHeight: 500 })).toBe(true)
  })
})
