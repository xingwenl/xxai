import { describe, expect, it } from 'vitest'
import type { ModelUsage } from '../../core'
import { sessionUsageView, usageChipView } from '../usage-view'

/** 截图里的那组数：总量 1,332,145 = 输入 1,319,322 + 输出 12,823。 */
const screenshotUsage: ModelUsage = {
  promptTokens: 1_319_322,
  completionTokens: 12_823,
  totalTokens: 1_332_145,
  cacheReadTokens: 1_239_936,
  model: 'deepseek/deepseek-v4.1-flash',
  provider: 'ds1'
}

describe('usageChipView', () => {
  it('chip 只给紧凑总量，明细卡标题右侧给精确值', () => {
    const view = usageChipView(screenshotUsage)

    expect(view?.text).toBe('用量 1.3M tok')
    expect(view?.title).toBe('本轮用量')
    expect(view?.totalText).toBe('1,332,145 tok')
  })

  it('明细行顺序与口径对齐 DSH：提供方/模型、缓存命中、未缓存输入、缓存读取、输出', () => {
    const view = usageChipView(screenshotUsage)

    expect(view?.rows).toEqual([
      { label: '提供方/模型', value: 'ds1 / deepseek/deepseek-v4.1-flash' },
      { label: '缓存命中', value: '94%' },
      { label: '未缓存输入', value: '79,386 tok' },
      { label: '缓存读取', value: '1,239,936 tok' },
      { label: '输出', value: '12,823 tok' }
    ])
  })

  it('provider 没报缓存字段时隐藏三行缓存相关明细，输出行始终保留', () => {
    const view = usageChipView({
      promptTokens: 10,
      completionTokens: 2,
      totalTokens: 12,
      model: 'gpt-4o-mini'
    })

    expect(view?.rows).toEqual([
      { label: '提供方/模型', value: 'gpt-4o-mini' },
      { label: '输出', value: '2 tok' }
    ])
  })

  it('只有 provider 或只有 model 时按单边展示', () => {
    expect(usageChipView({ ...screenshotUsage, model: undefined })?.rows[0]).toEqual({
      label: '提供方/模型',
      value: 'ds1'
    })
    expect(usageChipView({ ...screenshotUsage, provider: undefined })?.rows[0]).toEqual({
      label: '提供方/模型',
      value: 'deepseek/deepseek-v4.1-flash'
    })
  })

  it('没有用量时整块不渲染', () => {
    expect(usageChipView(null)).toBeNull()
    expect(usageChipView(undefined)).toBeNull()
  })
})

describe('sessionUsageView', () => {
  it('会话累计给总量与命中率，精确值放悬停提示', () => {
    const view = sessionUsageView(screenshotUsage)

    expect(view?.text).toBe('本会话累计 1.3M tok · 缓存命中 94%')
    expect(view?.detail).toBe('本会话累计 1,332,145 tok')
  })

  it('没有缓存口径时只给总量', () => {
    const view = sessionUsageView({
      promptTokens: 10,
      completionTokens: 2,
      totalTokens: 12
    })

    expect(view?.text).toBe('本会话累计 12 tok')
  })

  it('没有用量时返回 null', () => {
    expect(sessionUsageView(null)).toBeNull()
  })
})
