import { describe, expect, it } from 'vitest'
import { resolveHeaderName } from '../header-name'

describe('resolveHeaderName', () => {
  it('优先展示 client 名称', () => {
    expect(resolveHeaderName('ToolVerse', 'AI Assistant')).toBe('ToolVerse')
  })

  it('client 名称缺失时回退到 title', () => {
    expect(resolveHeaderName(undefined, '客服助手')).toBe('客服助手')
    expect(resolveHeaderName(null, '客服助手')).toBe('客服助手')
  })

  it('client 名称为空串或空白时回退到 title', () => {
    expect(resolveHeaderName('  ', '客服助手')).toBe('客服助手')
    expect(resolveHeaderName('', '客服助手')).toBe('客服助手')
  })

  it('两者都缺失时回退到默认名称', () => {
    expect(resolveHeaderName()).toBe('AI Assistant')
    expect(resolveHeaderName(undefined, '  ')).toBe('AI Assistant')
  })
})
