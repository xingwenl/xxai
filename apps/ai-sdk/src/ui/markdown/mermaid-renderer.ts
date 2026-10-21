// 内置 Mermaid 渲染器。
// 引擎来源按「显式注入 → 全局变量 → 动态 import」三级解析，任一环节不可用都降级为代码块，
// 避免把重引擎打进 SDK，也避免引擎缺失时破坏消息渲染。

import DOMPurify from 'dompurify'
import {
  MAX_DIAGRAM_SOURCE_LENGTH,
  createMarkdownFenceError,
  type MarkdownFenceRenderer
} from './fence-registry'
import { optionalEngineSpecifiers } from './optional-engines'

/** Mermaid 的最小接口定义：SDK 不依赖 mermaid 包及其类型声明 */
export interface MermaidLike {
  initialize(config: Record<string, unknown>): void
  render(id: string, code: string): { svg: string } | Promise<{ svg: string }>
}

/**
 * 引擎加载器：由宿主提供，形如 `() => import('mermaid')`。
 * 动态 import 的字面量必须写在宿主源码里，打包器才能在构建期切出独立 chunk；
 * SDK 只负责"何时调用、调用几次、失败后如何重试"这些加载策略。
 */
export type MermaidEngineLoader = () => Promise<
  MermaidLike | { default?: MermaidLike } | null | undefined
>

/** 可注入的引擎形态：实例 / loader / `null`（明确禁用） */
export type MermaidEngineInput = MermaidLike | null | MermaidEngineLoader

/** 可以覆盖 Mermaid 配置或生成 JS 链接的指令，来自未受信模型输出时必须剔除 */
const DISALLOWED_LINE_PREFIXES = ['%%{', 'click ']

/** 已知的 Mermaid 图类型关键字，用于判断流式输出是否已经形成可渲染的图定义 */
const DIAGRAM_KEYWORDS = [
  'graph',
  'flowchart',
  'sequenceDiagram',
  'classDiagram',
  'stateDiagram',
  'erDiagram',
  'journey',
  'gantt',
  'pie',
  'quadrantChart',
  'requirementDiagram',
  'gitGraph',
  'mindmap',
  'timeline',
  'zenuml',
  'sankey-beta',
  'xychart-beta',
  'block-beta',
  'packet-beta',
  'architecture-beta',
  'kanban',
  'C4Context'
]

const MAX_SVG_CACHE_ENTRIES = 50

let injectedEngine: MermaidEngineInput | undefined
let injectedEnginePromise: Promise<MermaidLike | null> | null = null
let enginePromise: Promise<MermaidLike | null> | null = null
let initializedConfigKey = ''
let renderSequence = 0
const svgCache = new Map<string, string>()

/**
 * 显式注入引擎；可传实例、loader（如 `() => import('mermaid')`）。
 * 传 `null` 表示明确禁用，`undefined` 表示恢复自动解析（全局变量 → 动态 import）。
 */
export function setMermaidEngine(engine: MermaidEngineInput | undefined): void {
  injectedEngine = engine
  injectedEnginePromise = null
  enginePromise = null
  initializedConfigKey = ''
  // 引擎可能换成不同版本或不同主题实现，缓存必须一起失效
  svgCache.clear()
}

export function clearMermaidCache(): void {
  svgCache.clear()
}

/**
 * 剔除 Mermaid 指令行。
 * `%%{...}%%` 可以覆盖安全相关配置，`click` 能在渲染结果里挂 JS 回调或链接，
 * 两者都会让未受信模型输出获得额外能力，因此在渲染前直接丢弃。
 */
export function sanitizeMermaidSource(code: string): string {
  return String(code || '')
    .split('\n')
    .filter((line) => {
      const trimmed = line.trimStart()
      return !DISALLOWED_LINE_PREFIXES.some((prefix) => trimmed.startsWith(prefix))
    })
    .join('\n')
}

/** 判断源码是否已形成可渲染的图定义（流式输出时可能只有半截语法） */
export function isMermaidSourceReady(code: string): boolean {
  const source = sanitizeMermaidSource(code).trim()
  if (!source || source.length > MAX_DIAGRAM_SOURCE_LENGTH) return false
  return DIAGRAM_KEYWORDS.some((keyword) => source.startsWith(keyword))
}

function mermaidConfig(theme: 'light' | 'dark'): Record<string, unknown> {
  return {
    startOnLoad: false,
    // 与 Streamdown、Dify 的生产配置保持一致：严格级别由 Mermaid 内部做标签清洗
    securityLevel: 'strict',
    suppressErrorRendering: true,
    theme: theme === 'dark' ? 'dark' : 'default',
    fontFamily: 'inherit',
    flowchart: { htmlLabels: false, useMaxWidth: true }
  }
}

/** 把 loader 的返回值归一化为引擎实例；模块命名空间走 `default` 兜底 */
function normalizeMermaidModule(
  module: MermaidLike | { default?: MermaidLike } | null | undefined
): MermaidLike | null {
  const candidate = (module as { default?: MermaidLike } | null)?.default ?? (module as MermaidLike | null)
  return candidate && typeof candidate.render === 'function' ? candidate : null
}

/**
 * 解析宿主注入的引擎。
 * 实例直接返回；loader 在首个图表挂载时才调用，并发挂载共用同一个 promise，
 * 失败后清空 promise，保证宿主稍后补齐依赖时后续图表仍能重试成功。
 */
async function resolveInjectedMermaid(): Promise<MermaidLike | null> {
  if (!injectedEngine) return null
  if (typeof injectedEngine !== 'function') return injectedEngine

  if (!injectedEnginePromise) {
    const loader = injectedEngine
    injectedEnginePromise = Promise.resolve()
      .then(() => loader())
      .then((module) => normalizeMermaidModule(module))
      .catch(() => null)
  }
  const resolved = await injectedEnginePromise
  if (!resolved) injectedEnginePromise = null
  return resolved
}

async function resolveMermaid(): Promise<MermaidLike | null> {
  if (injectedEngine !== undefined) return resolveInjectedMermaid()

  const globalEngine = (globalThis as { mermaid?: MermaidLike }).mermaid
  if (globalEngine && typeof globalEngine.render === 'function') {
    enginePromise = null
    return globalEngine
  }

  if (!enginePromise) {
    // 用非字面量说明符动态导入：既不引入 mermaid 依赖与类型，也避免打包器把引擎内联进产物。
    // 说明符取自跨模块的可变映射，防止常量折叠把它还原成静态 `import("mermaid")`。
    const specifier = optionalEngineSpecifiers.mermaid
    enginePromise = import(/* @vite-ignore */ specifier)
      .then((module) => ((module as { default?: MermaidLike }).default || (module as MermaidLike)))
      .catch(() => null)
  }
  const resolved = await enginePromise
  // 解析失败不长期缓存：宿主可能在页面加载后才挂上全局引擎，后续消息需要能重试成功
  if (!resolved) enginePromise = null
  return resolved
}

function sanitizeSvg(svg: string): string {
  // 无 DOM 环境（SSR、Node 测试）下 DOMPurify 不提供 sanitize；此时也不存在可注入的 DOM，
  // 直接返回原文，浏览器环境下必定走下面的清洗分支。
  if (typeof DOMPurify.sanitize !== 'function') return svg
  return DOMPurify.sanitize(svg, {
    USE_PROFILES: { svg: true, svgFilters: true },
    ADD_ATTR: ['class', 'style', 'transform-origin', 'dominant-baseline']
  })
}

/**
 * 渲染 Mermaid 源码为 SVG 字符串。
 * 返回 `null` 表示当前不可渲染（引擎缺失、源码未就绪或超长），由调用方降级为代码块。
 */
export async function renderMermaidToSvg(code: string, theme: 'light' | 'dark'): Promise<string | null> {
  const source = sanitizeMermaidSource(code).trim()
  if (!isMermaidSourceReady(source)) return null

  const engine = await resolveMermaid()
  if (!engine) return null

  const cacheKey = `${theme}\u0000${source}`
  const cached = svgCache.get(cacheKey)
  if (cached) return cached

  if (initializedConfigKey !== theme) {
    engine.initialize(mermaidConfig(theme))
    initializedConfigKey = theme
  }

  const result = await engine.render(`xxai-mermaid-${++renderSequence}`, source)
  const raw = String(result?.svg || '')
  if (!raw) return null

  const svg = sanitizeSvg(raw)
  svgCache.set(cacheKey, svg)
  if (svgCache.size > MAX_SVG_CACHE_ENTRIES) {
    const oldest = svgCache.keys().next().value
    if (oldest) svgCache.delete(oldest)
  }
  return svg
}

export const mermaidFenceRenderer: MarkdownFenceRenderer = {
  language: 'mermaid',
  async mount(element, code, context) {
    const source = sanitizeMermaidSource(code).trim()
    if (!isMermaidSourceReady(source)) {
      throw createMarkdownFenceError('source-not-ready', 'mermaid source is empty, oversized or not a diagram')
    }
    const svg = await renderMermaidToSvg(source, context.theme)
    if (!svg) throw createMarkdownFenceError('engine-missing', 'mermaid engine is not available')
    element.innerHTML = svg
  }
}
