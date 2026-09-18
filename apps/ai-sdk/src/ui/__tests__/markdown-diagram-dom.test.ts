// @vitest-environment jsdom
// 浏览器路径验证：占位节点水合、SVG 清洗、自定义渲染器与卸载清理。
// 依赖 jsdom 环境（package.json 中声明 devDependency），默认的 node 环境无法覆盖该路径。
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, ref, type App } from 'vue'
import MarkdownContent from '../components/MarkdownContent.vue'
import { configureMarkdownDiagrams, registerMarkdownFenceRenderer, unregisterMarkdownFenceRenderer } from '../markdown'
import { setMermaidEngine, type MermaidLike } from '../markdown/mermaid-renderer'
import { setEChartsEngine, type EChartsLike } from '../markdown/echarts-renderer'

let app: App | null = null
let container: HTMLElement | null = null

function mountMarkdown(text: string) {
  container = document.createElement('div')
  document.body.appendChild(container)
  app = createApp({ render: () => h(MarkdownContent, { text }) })
  app.mount(container)
  return container
}

async function waitFor(check: () => boolean, timeout = 2000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (check()) return true
    await new Promise((resolve) => setTimeout(resolve, 10))
  }
  return check()
}

afterEach(() => {
  app?.unmount()
  container?.remove()
  app = null
  container = null
  configureMarkdownDiagrams({ mermaid: null, echarts: null })
  unregisterMarkdownFenceRenderer('test-vega')
  document.body.innerHTML = ''
})

describe('Markdown 图表浏览器路径', () => {
  it('mermaid 围栏水合成 SVG，且清洗掉引擎产物里的脚本', async () => {
    const engine: MermaidLike = {
      initialize: vi.fn(),
      render: vi.fn(() => ({
        svg: '<svg data-engine="fake"><script>window.__xss = 1</script><path d="M0 0" /></svg>'
      }))
    }
    setMermaidEngine(engine)

    const root = mountMarkdown('```mermaid\ngraph TD\nA --> B\n```')
    await waitFor(() => Boolean(root.querySelector('svg[data-engine="fake"]')))

    expect(root.querySelector('svg[data-engine="fake"]')).toBeTruthy()
    expect(root.querySelector('svg path')).toBeTruthy()
    expect(root.querySelector('script')).toBeNull()
    expect(root.querySelector('pre code.language-mermaid')).toBeNull()
    // 源码不进入页面文本
    expect(root.textContent).not.toContain('graph TD')
    // 占位节点仍在原位，供后续卸载清理
    expect(root.querySelector('[data-xxai-diagram-id]')).toBeTruthy()
  })

  it('未注册语言与空语言保持代码块', async () => {
    const root = mountMarkdown('```python\nprint(1)\n```\n\n```\nplain\n```')
    await new Promise((resolve) => setTimeout(resolve, 20))

    expect(root.querySelector('pre code.language-python')?.textContent).toContain('print(1)')
    expect(root.querySelector('.xxai-markdown-diagram')).toBeNull()
  })

  it('引擎不可用时降级为代码块并给出提示', async () => {
    const root = mountMarkdown('```mermaid\ngraph TD\nA --> B\n```')
    await waitFor(() => Boolean(root.querySelector('.xxai-markdown-diagram-hint')))

    expect(root.querySelector('pre code.language-mermaid')?.textContent).toContain('graph TD')
    expect(root.querySelector('.xxai-markdown-diagram-hint')?.textContent).toContain('未检测到 Mermaid 引擎')
    expect(root.querySelector('svg')).toBeNull()
  })

  it('echarts 围栏配置不是 JSON 对象时降级，并说明具体原因', async () => {
    const instance = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }
    setEChartsEngine({ init: vi.fn(() => instance) } as EChartsLike)

    const root = mountMarkdown('```echarts\necharts.init(document.body)\n```')
    await waitFor(() => Boolean(root.querySelector('.xxai-markdown-diagram-hint')))

    expect(instance.setOption).not.toHaveBeenCalled()
    expect(root.querySelector('.xxai-markdown-diagram-hint')?.textContent).toContain('不是合法的 JSON 对象')
    expect(root.querySelector('pre code.language-echarts')?.textContent).toContain('echarts.init')
  })

  it('宿主注册的自定义渲染器会被调用，并在卸载时清理', async () => {
    const cleanup = vi.fn()
    const mount = vi.fn((element: HTMLElement, _code: string) => {
      element.innerHTML = '<div data-vega="1"></div>'
      return cleanup
    })
    registerMarkdownFenceRenderer('test-vega', { mount })

    const root = mountMarkdown('```test-vega\n{"mark": "bar"}\n```')
    await waitFor(() => Boolean(root.querySelector('[data-vega="1"]')))

    expect(mount).toHaveBeenCalledTimes(1)
    expect(mount.mock.calls[0][1]).toContain('"mark"')

    app?.unmount()
    app = null
    expect(cleanup).toHaveBeenCalledTimes(1)
  })

  it('echarts 围栏初始化图表，卸载时释放实例', async () => {
    const instance = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }
    const init = vi.fn(() => instance)
    setEChartsEngine({ init } as EChartsLike)

    const root = mountMarkdown('```echarts\n{"series": []}\n```')
    await waitFor(() => instance.setOption.mock.calls.length > 0)

    expect(init).toHaveBeenCalledTimes(1)
    expect(instance.setOption).toHaveBeenCalledWith({ series: [] })

    app?.unmount()
    app = null
    expect(instance.dispose).toHaveBeenCalledTimes(1)
  })

  it('文本更新后重新水合，旧的图表实例被释放', async () => {
    const instance = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }
    setEChartsEngine({ init: vi.fn(() => instance) } as EChartsLike)

    const text = ref('```echarts\n{"series": [1]}\n```')
    container = document.createElement('div')
    document.body.appendChild(container)
    app = createApp({ render: () => h(MarkdownContent, { text: text.value }) })
    app.mount(container)

    await waitFor(() => instance.setOption.mock.calls.length === 1)
    text.value = '```echarts\n{"series": [2]}\n```'
    await waitFor(() => instance.setOption.mock.calls.length === 2)
    await waitFor(() => instance.dispose.mock.calls.length === 1)

    // 源码已更新到新图表配置，旧实例被释放
    expect(instance.setOption).toHaveBeenLastCalledWith({ series: [2] })
    expect(instance.dispose).toHaveBeenCalled()
  })
})
