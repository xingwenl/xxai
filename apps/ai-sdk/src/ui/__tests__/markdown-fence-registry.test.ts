import { describe, expect, it, afterEach } from 'vitest'
// 引入装配入口以触发内置渲染器注册（mermaid / echarts 默认可用）
import '../markdown'
import {
  getMarkdownFenceRenderer,
  listMarkdownFenceLanguages,
  normalizeFenceLanguage,
  registerMarkdownFenceRenderer,
  unregisterMarkdownFenceRenderer
} from '../markdown/fence-registry'

const registeredLanguages = ['test-vega', 'test-plotly']

afterEach(() => {
  for (const language of registeredLanguages) unregisterMarkdownFenceRenderer(language)
})

describe('Markdown 围栏渲染器注册表', () => {
  it('注册后可查询，语言名按小写归一化', () => {
    registerMarkdownFenceRenderer('Test-Vega', { mount: () => undefined })

    expect(getMarkdownFenceRenderer('test-vega')).toBeDefined()
    expect(getMarkdownFenceRenderer('TEST-VEGA')).toBeDefined()
    expect(getMarkdownFenceRenderer(' test-vega ')).toBeDefined()
    expect(getMarkdownFenceRenderer('test-vega')?.language).toBe('test-vega')
  })

  it('同一语言重复注册时后者覆盖前者', () => {
    const first = () => undefined
    const second = () => undefined
    registerMarkdownFenceRenderer('test-vega', { mount: first })
    registerMarkdownFenceRenderer('test-vega', { mount: second })

    expect(getMarkdownFenceRenderer('test-vega')?.mount).toBe(second)
  })

  it('注销后查询为空，未注册语言与空语言都返回 undefined', () => {
    registerMarkdownFenceRenderer('test-plotly', { mount: () => undefined })
    unregisterMarkdownFenceRenderer('test-plotly')

    expect(getMarkdownFenceRenderer('test-plotly')).toBeUndefined()
    expect(getMarkdownFenceRenderer('never-registered')).toBeUndefined()
    expect(getMarkdownFenceRenderer('')).toBeUndefined()
  })

  it('忽略空语言名与缺少 mount 的渲染器', () => {
    registerMarkdownFenceRenderer('   ', { mount: () => undefined })
    registerMarkdownFenceRenderer('test-vega', {} as never)

    expect(getMarkdownFenceRenderer('test-vega')).toBeUndefined()
    expect(normalizeFenceLanguage('   ')).toBe('')
  })

  it('内置语言默认已注册，列表按字母序返回', () => {
    const languages = listMarkdownFenceLanguages()

    expect(languages).toContain('mermaid')
    expect(languages).toContain('echarts')
    expect([...languages].sort()).toEqual(languages)
  })
})
