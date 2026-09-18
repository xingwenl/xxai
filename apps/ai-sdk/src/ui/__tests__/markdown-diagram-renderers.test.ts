import { describe, expect, it, afterEach, vi } from 'vitest'

// 保证「运行时加载失败」这条路径可确定性复现：本机若装了真实引擎，默认会加载成功
vi.mock('mermaid', () => {
  throw new Error('mermaid is not installed in this test environment')
})
vi.mock('echarts', () => {
  throw new Error('echarts is not installed in this test environment')
})
import '../markdown'
import {
  clearMermaidCache,
  isMermaidSourceReady,
  mermaidFenceRenderer,
  renderMermaidToSvg,
  sanitizeMermaidSource,
  setMermaidEngine,
  type MermaidLike
} from '../markdown/mermaid-renderer'
import {
  echartsFenceRenderer,
  parseEChartsOption,
  setEChartsEngine,
  type EChartsLike
} from '../markdown/echarts-renderer'
import { MAX_DIAGRAM_SOURCE_LENGTH } from '../markdown/fence-registry'
import { getMarkdownFenceErrorCode } from '../markdown/fence-registry'

function fakeMermaid(svg = '<svg data-test="ok"><path d="M0 0" /></svg>') {
  const initialize = vi.fn((_config: Record<string, unknown>) => undefined)
  const render = vi.fn((_id: string, _code: string) => ({ svg }))
  const engine: MermaidLike = { initialize, render }
  return { engine, initialize, render }
}

function fakeElement() {
  return { innerHTML: '', style: {} } as unknown as HTMLElement
}

afterEach(() => {
  setMermaidEngine(undefined)
  setEChartsEngine(undefined)
  clearMermaidCache()
  delete (globalThis as { mermaid?: unknown }).mermaid
  delete (globalThis as { echarts?: unknown }).echarts
})

describe('Mermaid 源码清洗与就绪判断', () => {
  it('剔除可覆盖配置的 init 指令与 click 交互指令', () => {
    const source = [
      'graph TD',
      '%%{init: {"securityLevel": "loose"}}%%',
      'A --> B',
      'click A "javascript:alert(1)"',
      '  click B callback'
    ].join('\n')

    const sanitized = sanitizeMermaidSource(source)

    expect(sanitized).not.toContain('%%{')
    expect(sanitized).not.toContain('click ')
    expect(sanitized).toContain('A --> B')
  })

  it('只有形成图定义且未超长时才认为可渲染', () => {
    expect(isMermaidSourceReady('graph TD\nA --> B')).toBe(true)
    expect(isMermaidSourceReady('sequenceDiagram\nA->>B: hi')).toBe(true)
    expect(isMermaidSourceReady('')).toBe(false)
    expect(isMermaidSourceReady('这是一段普通说明')).toBe(false)
    expect(isMermaidSourceReady(`graph TD\n${'A-->B\n'.repeat(MAX_DIAGRAM_SOURCE_LENGTH)}`)).toBe(false)
  })
})

describe('Mermaid 渲染器', () => {
  it('使用显式注入的引擎渲染，并以严格安全级别初始化', async () => {
    const { engine, initialize, render } = fakeMermaid()
    setMermaidEngine(engine)

    const svg = await renderMermaidToSvg('graph TD\nA --> B', 'light')

    expect(svg).toContain('<svg')
    expect(render).toHaveBeenCalledTimes(1)
    expect(initialize.mock.calls[0][0]).toMatchObject({
      startOnLoad: false,
      securityLevel: 'strict',
      suppressErrorRendering: true
    })
  })

  it('把清洗后的源码交给引擎，指令行不会到达引擎', async () => {
    const { engine, render } = fakeMermaid()
    setMermaidEngine(engine)

    await renderMermaidToSvg('graph TD\n%%{init: {}}%%\nA --> B', 'light')

    expect(render.mock.calls[0][1]).not.toContain('%%{')
  })

  it('相同源码与主题命中缓存，主题变化时重新渲染', async () => {
    const { engine, render } = fakeMermaid()
    setMermaidEngine(engine)

    await renderMermaidToSvg('graph TD\nA --> B', 'light')
    await renderMermaidToSvg('graph TD\nA --> B', 'light')
    expect(render).toHaveBeenCalledTimes(1)

    await renderMermaidToSvg('graph TD\nA --> B', 'dark')
    expect(render).toHaveBeenCalledTimes(2)
  })

  it('源码未就绪时不调用引擎', async () => {
    const { engine, render } = fakeMermaid()
    setMermaidEngine(engine)

    await expect(renderMermaidToSvg('半截输出', 'light')).resolves.toBeNull()
    expect(render).not.toHaveBeenCalled()
  })

  it('引擎不可用时返回 null（动态 import 失败后降级）', async () => {
    await expect(renderMermaidToSvg('graph TD\nA --> B', 'light')).resolves.toBeNull()
  })

  it('引擎不可用时抛出 engine-missing，源码未就绪时抛出 source-not-ready', async () => {
    await expect(
      mermaidFenceRenderer.mount(fakeElement(), 'graph TD\nA --> B', { theme: 'light', language: 'mermaid' })
    ).rejects.toSatisfy((error) => getMarkdownFenceErrorCode(error) === 'engine-missing')

    setMermaidEngine(fakeMermaid().engine)
    await expect(
      mermaidFenceRenderer.mount(fakeElement(), '半截输出', { theme: 'light', language: 'mermaid' })
    ).rejects.toSatisfy((error) => getMarkdownFenceErrorCode(error) === 'source-not-ready')
  })

  it('首次解析失败后不永久缓存，宿主后续挂上全局引擎仍能重试成功', async () => {
    await expect(renderMermaidToSvg('graph TD\nA --> B', 'light')).resolves.toBeNull()

    ;(globalThis as { mermaid?: unknown }).mermaid = fakeMermaid().engine

    await expect(renderMermaidToSvg('graph TD\nA --> B', 'light')).resolves.toContain('<svg')
  })

  it('显式禁用引擎时不渲染', async () => {
    ;(globalThis as { mermaid?: unknown }).mermaid = fakeMermaid().engine
    setMermaidEngine(null)

    await expect(renderMermaidToSvg('graph TD\nA --> B', 'light')).resolves.toBeNull()
  })

  it('渲染失败时把错误抛给调用方，由其降级为代码块', async () => {
    const engine: MermaidLike = {
      initialize: () => undefined,
      render: () => {
        throw new Error('parse error')
      }
    }
    setMermaidEngine(engine)

    await expect(renderMermaidToSvg('graph TD\nA --> B', 'light')).rejects.toThrow('parse error')
  })
})

describe('ECharts 渲染器', () => {
  function fakeEcharts() {
    const instance = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }
    const init = vi.fn((_element: HTMLElement, _theme?: string) => instance)
    const engine: EChartsLike = { init }
    return { engine, init, instance }
  }

  it('只接受 JSON 对象配置', () => {
    expect(parseEChartsOption('{"series": []}')).toEqual({ series: [] })
    expect(parseEChartsOption('[1, 2]')).toBeNull()
    expect(parseEChartsOption('"option"')).toBeNull()
    expect(parseEChartsOption('function () { return 1 }')).toBeNull()
    expect(parseEChartsOption('{ series: [] }')).toBeNull()
    expect(parseEChartsOption('   ')).toBeNull()
    expect(parseEChartsOption(`{"a":"${'x'.repeat(MAX_DIAGRAM_SOURCE_LENGTH)}"}`)).toBeNull()
  })

  it('容忍尾随逗号与注释，但不执行任何 JS', () => {
    expect(parseEChartsOption('{ "series": [], }')).toEqual({ series: [] })
    expect(parseEChartsOption('{ // 说明\n "series": [] }')).toEqual({ series: [] })
    expect(parseEChartsOption('{ /* 说明 */ "series": [1, 2,] }')).toEqual({ series: [1, 2] })
    // 字符串内部的内容必须原样保留，不能被注释/逗号规则破坏
    expect(parseEChartsOption('{ "title": { "text": "https://a.test/x,}" } }')).toEqual({
      title: { text: 'https://a.test/x,}' }
    })
    expect(parseEChartsOption('{ series: [] }')).toBeNull()
    expect(parseEChartsOption('{ "formatter": (v) => v }')).toBeNull()
  })

  it('注入引擎时初始化图表并写入配置，深色主题透传给 init', async () => {
    const { engine, init, instance } = fakeEcharts()
    setEChartsEngine(engine)

    await echartsFenceRenderer.mount(fakeElement(), '{"series": []}', { theme: 'dark', language: 'echarts' })

    expect(init.mock.calls[0][1]).toBe('dark')
    expect(instance.setOption).toHaveBeenCalledWith({ series: [] })
  })

  it('返回的清理函数会释放图表实例', async () => {
    const { engine, instance } = fakeEcharts()
    setEChartsEngine(engine)

    const cleanup = await echartsFenceRenderer.mount(fakeElement(), '{"series": []}', {
      theme: 'light',
      language: 'echarts'
    })

    expect(instance.dispose).not.toHaveBeenCalled()
    if (typeof cleanup === 'function') cleanup()
    expect(instance.dispose).toHaveBeenCalledTimes(1)
  })

  it('配置不是 JSON 对象时拒绝渲染', async () => {
    const { engine, init } = fakeEcharts()
    setEChartsEngine(engine)

    await expect(echartsFenceRenderer.mount(fakeElement(), 'console.log(1)', {
      theme: 'light',
      language: 'echarts'
    })).rejects.toThrow()
    expect(init).not.toHaveBeenCalled()
  })

  it('区分 option-invalid 与 engine-missing 两种降级原因', async () => {
    const { engine } = fakeEcharts()
    setEChartsEngine(engine)
    await expect(
      echartsFenceRenderer.mount(fakeElement(), 'echarts.init(document.body)', { theme: 'light', language: 'echarts' })
    ).rejects.toSatisfy((error) => getMarkdownFenceErrorCode(error) === 'option-invalid')

    setEChartsEngine(undefined)
    await expect(
      echartsFenceRenderer.mount(fakeElement(), '{"series": []}', { theme: 'light', language: 'echarts' })
    ).rejects.toSatisfy((error) => getMarkdownFenceErrorCode(error) === 'engine-missing')
  })

  it('引擎不可用时拒绝渲染', async () => {
    await expect(echartsFenceRenderer.mount(fakeElement(), '{"series": []}', {
      theme: 'light',
      language: 'echarts'
    })).rejects.toThrow()
  })
})
