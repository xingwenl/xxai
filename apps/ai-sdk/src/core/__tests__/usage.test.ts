import { describe, expect, it } from 'vitest'
import {
  cacheHitPercent,
  parseUsage,
  sumUsage,
  uncachedPromptTokens
} from '../usage'

describe('parseUsage', () => {
  it('解析后端蛇形（线协议）形状，缓存与模型信息一并带出', () => {
    expect(
      parseUsage({
        prompt_tokens: 120,
        completion_tokens: 8,
        total_tokens: 128,
        cache_read_tokens: 90,
        cache_creation_tokens: 3,
        model: 'deepseek-v4-pro',
        provider: 'deepseek'
      })
    ).toEqual({
      promptTokens: 120,
      completionTokens: 8,
      totalTokens: 128,
      cacheReadTokens: 90,
      cacheCreationTokens: 3,
      model: 'deepseek-v4-pro',
      provider: 'deepseek'
    })
  })

  it('兼容驼峰拼写（宿主可能自行拼装 metadata.usage）', () => {
    expect(
      parseUsage({
        promptTokens: 10,
        completionTokens: 2,
        totalTokens: 12,
        cacheReadTokens: 4
      })
    ).toMatchObject({ promptTokens: 10, completionTokens: 2, totalTokens: 12, cacheReadTokens: 4 })
  })

  it('total 缺失时用输入 + 输出推导，仍缺失则整体作废', () => {
    expect(parseUsage({ prompt_tokens: 10, completion_tokens: 2 })).toMatchObject({
      totalTokens: 12
    })
    expect(parseUsage({ prompt_tokens: 10 })).toBeNull()
    expect(parseUsage({ completion_tokens: 2 })).toBeNull()
  })

  it('缓存字段没报时不产出该键（与 0 区分，UI 据此隐藏整行）', () => {
    const usage = parseUsage({ prompt_tokens: 10, completion_tokens: 2, total_tokens: 12 })

    expect(usage).not.toBeNull()
    expect(usage && 'cacheReadTokens' in usage).toBe(false)
  })

  it('拒绝非对象、负数与非有限数', () => {
    expect(parseUsage(null)).toBeNull()
    expect(parseUsage('usage')).toBeNull()
    expect(parseUsage([])).toBeNull()
    expect(parseUsage({ prompt_tokens: -1, completion_tokens: 2, total_tokens: 1 })).toBeNull()
    expect(
      parseUsage({ prompt_tokens: Number.NaN, completion_tokens: 2, total_tokens: 2 })
    ).toBeNull()
  })
})

describe('sumUsage', () => {
  it('逐轮累加三项总量与已报的缓存计数', () => {
    const total = sumUsage([
      { promptTokens: 100, completionTokens: 10, totalTokens: 110, cacheReadTokens: 60 },
      { promptTokens: 50, completionTokens: 5, totalTokens: 55, cacheReadTokens: 40 },
      null,
      undefined
    ])

    expect(total).toEqual({
      promptTokens: 150,
      completionTokens: 15,
      totalTokens: 165,
      cacheReadTokens: 100
    })
  })

  it('某几轮没报缓存时，合计只累加报了的轮次', () => {
    const total = sumUsage([
      { promptTokens: 10, completionTokens: 1, totalTokens: 11, cacheReadTokens: 6 },
      { promptTokens: 10, completionTokens: 1, totalTokens: 11 }
    ])

    expect(total?.cacheReadTokens).toBe(6)
  })

  it('全为空时返回 null，且不修改入参对象', () => {
    expect(sumUsage([])).toBeNull()
    expect(sumUsage([null, undefined])).toBeNull()

    const first = { promptTokens: 1, completionTokens: 1, totalTokens: 2, model: 'm' }
    const total = sumUsage([first, { promptTokens: 1, completionTokens: 1, totalTokens: 2 }])

    expect(total?.promptTokens).toBe(2)
    expect(total?.model).toBe('m')
    expect(first.promptTokens).toBe(1)
  })
})

describe('cacheHitPercent / uncachedPromptTokens', () => {
  const usage = {
    promptTokens: 120,
    completionTokens: 8,
    totalTokens: 128,
    cacheReadTokens: 90
  }

  it('命中率按缓存读取 / 总输入，四舍五入成整数百分比', () => {
    expect(cacheHitPercent(usage)).toBe(75)
  })

  it('未缓存输入 = 总输入 − 缓存读取，异常数据按 0 截断', () => {
    expect(uncachedPromptTokens(usage)).toBe(30)
    expect(uncachedPromptTokens({ ...usage, cacheReadTokens: 200 })).toBe(0)
  })

  it('没报缓存或无输入 token 时两个口径都为 null', () => {
    const noCache = { promptTokens: 120, completionTokens: 8, totalTokens: 128 }

    expect(cacheHitPercent(noCache)).toBeNull()
    expect(uncachedPromptTokens(noCache)).toBeNull()
    expect(cacheHitPercent({ ...noCache, promptTokens: 0 })).toBeNull()
  })

  it('缓存读取超过总输入（口径差异）时命中率封顶 100%', () => {
    expect(cacheHitPercent({ ...usage, cacheReadTokens: 300 })).toBe(100)
  })
})
