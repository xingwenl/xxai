// Markdown 渲染管线：把消息文本渲染为 HTML，并把图表围栏抽成占位节点。
// 这里只做同步的字符串处理，DOM 相关的水合由 MarkdownContent.vue 负责，便于在无 DOM 环境单测。

import MarkdownIt from 'markdown-it'
import { getMarkdownFenceRenderer, normalizeFenceLanguage } from './fence-registry'

export interface MarkdownDiagramSource {
  language: string
  code: string
}

export interface MarkdownRenderResult {
  html: string
  /** 占位节点 id → 图表源码，由水合阶段交给对应渲染器 */
  diagrams: Map<string, MarkdownDiagramSource>
}

interface RenderEnv {
  diagrams: Map<string, MarkdownDiagramSource>
  diagramSequence: number
}

function escapeAttribute(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[character] || character)
}

export function createMarkdownParser(): InstanceType<typeof MarkdownIt> {
  const parser = new MarkdownIt({
    html: false,
    linkify: true,
    breaks: true,
    typographer: true
  })

  // 先把图片地址放入 data 属性，避免 v-html 插入时由浏览器直接发起未授权请求。
  parser.renderer.rules.image = (tokens, index, _options, _env, _self) => {
    const token = tokens[index]
    const source = String(token.attrGet('src') || '')
    const alt = String(token.content || '')
    const title = token.attrGet('title')
    const titleAttribute = title ? ` title="${escapeAttribute(String(title))}"` : ''
    return `<img data-xxai-image-src="${escapeAttribute(source)}" alt="${escapeAttribute(alt)}"${titleAttribute}>`
  }

  // 保留 markdown-it 默认围栏规则：未注册语言（含普通代码块）必须与改动前完全一致。
  const defaultFenceRule = parser.renderer.rules.fence!
  parser.renderer.rules.fence = (tokens, index, options, env, self) => {
    const token = tokens[index]
    const language = normalizeFenceLanguage(String(token.info || '').trim().split(/\s+/)[0] || '')
    const renderer = language ? getMarkdownFenceRenderer(language) : undefined
    if (!renderer) return defaultFenceRule(tokens, index, options, env, self)

    // 源码只放进 env 映射，不写进 DOM 属性：避免大段源码的转义问题，也避免源码出现在页面文本里
    const target = env as unknown as RenderEnv
    const id = `xxai-diagram-${target.diagramSequence++}`
    target.diagrams.set(id, { language, code: token.content })
    return `<div class="xxai-markdown-diagram" data-xxai-diagram-lang="${escapeAttribute(language)}" data-xxai-diagram-id="${id}"></div>\n`
  }

  return parser
}

const parser = createMarkdownParser()

export function renderMarkdown(text?: string | null): MarkdownRenderResult {
  const env: RenderEnv = { diagrams: new Map(), diagramSequence: 0 }
  const html = parser.render(String(text || ''), env as unknown as Record<string, unknown>)
  return { html, diagrams: env.diagrams }
}
