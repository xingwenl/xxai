import { describe, expect, it } from 'vitest'
import {
  parseWindowRect,
  serializeWindowRect,
} from '../window-storage'

describe('window storage', () => {
  it('round-trips a rect through serialize and parse', () => {
    const rect = { x: 120, y: 80, width: 430, height: 680 }

    expect(parseWindowRect(serializeWindowRect(rect))).toEqual(rect)
  })

  it('returns null for empty or corrupted payloads', () => {
    expect(parseWindowRect(null)).toBeNull()
    expect(parseWindowRect('')).toBeNull()
    expect(parseWindowRect('not-json')).toBeNull()
    expect(parseWindowRect('{"x":1}')).toBeNull()
  })

  it('rejects non-finite or non-positive sizes', () => {
    expect(parseWindowRect('{"x":1,"y":2,"width":0,"height":10}')).toBeNull()
    expect(parseWindowRect('{"x":1,"y":2,"width":10,"height":-5}')).toBeNull()
    expect(parseWindowRect('{"x":1,"y":2,"width":NaN,"height":10}')).toBeNull()
    expect(parseWindowRect('{"x":"1","y":2,"width":10,"height":10}')).toBeNull()
  })
})
