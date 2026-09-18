import MarkdownIt from 'markdown-it'
import { afterEach, describe, expect, it } from 'vitest'
import '../markdown'
import { registerMarkdownFenceRenderer, unregisterMarkdownFenceRenderer } from '../markdown/fence-registry'
import { renderMarkdown } from '../markdown/pipeline'

afterEach(() => {
  unregisterMarkdownFenceRenderer('test-vega')
})

describe('MarkdownContent rendering pipeline', () => {
  it('renders markdown syntax and strips unsafe HTML', () => {
    const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true })
    const html = markdown.render('# 标题\n\n**重点**\n\n<script>alert(1)</script>')

    expect(html).toContain('<h1>标题</h1>')
    expect(html).toContain('<strong>重点</strong>')
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
  })

  it('未注册语言的围栏保持普通代码块', () => {
    const { html, diagrams } = renderMarkdown('```python\nprint(1)\n```')

    expect(html).toContain('<pre><code class="language-python">')
    expect(html).toContain('print(1)')
    expect(html).not.toContain('xxai-markdown-diagram')
    expect(diagrams.size).toBe(0)
  })

  it('内置 mermaid 围栏输出占位节点，源码只进入映射', () => {
    const { html, diagrams } = renderMarkdown('```mermaid\ngraph TD\nA --> B\n```')

    expect(html).toContain('class="xxai-markdown-diagram"')
    expect(html).toContain('data-xxai-diagram-lang="mermaid"')
    expect(html).toContain('data-xxai-diagram-id="xxai-diagram-0"')
    // 源码不写入 DOM，避免转义与泄漏问题
    expect(html).not.toContain('graph TD')
    expect(diagrams.get('xxai-diagram-0')).toEqual({
      language: 'mermaid',
      code: 'graph TD\nA --> B\n'
    })
  })

  it('宿主注册的自定义语言同样渲染，并按出现顺序生成占位 id', () => {
    registerMarkdownFenceRenderer('test-vega', { mount: () => undefined })

    const { html, diagrams } = renderMarkdown([
      '```test-vega',
      '{"mark": "bar"}',
      '```',
      '',
      '```mermaid',
      'pie title x',
      '```'
    ].join('\n'))

    expect(html).toContain('data-xxai-diagram-lang="test-vega"')
    expect(html).toContain('data-xxai-diagram-id="xxai-diagram-0"')
    expect(html).toContain('data-xxai-diagram-id="xxai-diagram-1"')
    expect(diagrams.get('xxai-diagram-1')?.language).toBe('mermaid')
  })

  it('围栏语言大小写不敏感，附加信息不参与匹配', () => {
    const { html, diagrams } = renderMarkdown('```Mermaid title="图"\ngraph TD\nA --> B\n```')

    expect(diagrams.get('xxai-diagram-0')?.language).toBe('mermaid')
    expect(html).not.toContain('language-Mermaid')
  })

  it('每次渲染重建占位 id，不会残留上一次的图表源码', () => {
    const first = renderMarkdown('```mermaid\ngraph TD\nA --> B\n```')
    const second = renderMarkdown('```mermaid\npie title 占比\n```')

    expect(first.diagrams.get('xxai-diagram-0')?.code).toContain('A --> B')
    expect(second.diagrams.size).toBe(1)
    expect(second.diagrams.get('xxai-diagram-0')?.code).toContain('占比')
  })

  it('图表源码中的脚本不会进入 HTML 文本', () => {
    const { html } = renderMarkdown('```mermaid\ngraph TD\nA[<script>alert(1)</script>] --> B\n```')

    expect(html).not.toContain('<script')
    expect(html).toContain('data-xxai-diagram-id')
  })
})
