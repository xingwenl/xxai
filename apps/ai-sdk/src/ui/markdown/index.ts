// Markdown 图表能力的装配入口。
// 内置 mermaid / echarts 两个渲染器，并允许宿主用同一接缝注册任意语言的渲染器。

import {
  registerMarkdownFenceRenderer,
  unregisterMarkdownFenceRenderer
} from './fence-registry'
import { mermaidFenceRenderer, setMermaidEngine, type MermaidEngineInput } from './mermaid-renderer'
import { echartsFenceRenderer, setEChartsEngine, type EChartsEngineInput } from './echarts-renderer'

export {
  MAX_DIAGRAM_SOURCE_LENGTH,
  createMarkdownFenceError,
  getMarkdownFenceRenderer,
  getMarkdownFenceErrorCode,
  listMarkdownFenceLanguages,
  normalizeFenceLanguage,
  registerMarkdownFenceRenderer,
  unregisterMarkdownFenceRenderer,
  type MarkdownFenceCleanup,
  type MarkdownFenceContext,
  type MarkdownFenceErrorCode,
  type MarkdownFenceRenderer,
  type MarkdownFenceRendererInput
} from './fence-registry'
export {
  sanitizeMermaidSource,
  isMermaidSourceReady,
  type MermaidEngineInput,
  type MermaidEngineLoader,
  type MermaidLike
} from './mermaid-renderer'
export {
  parseEChartsOption,
  type EChartsEngineInput,
  type EChartsEngineLoader,
  type EChartsInstanceLike,
  type EChartsLike
} from './echarts-renderer'

export interface MarkdownDiagramOptions {
  /**
   * Mermaid 引擎：可直接传实例，也可传 loader（如 `() => import('mermaid')`）。
   * loader 会在首个 mermaid 图表挂载时才被调用；`null` 表示禁用 Mermaid 渲染。
   */
  mermaid?: MermaidEngineInput
  /**
   * ECharts 引擎：可直接传实例，也可传 loader（如 `() => import('echarts')`）。
   * loader 会在首个 echarts 图表挂载时才被调用；`null` 表示禁用 ECharts 渲染。
   */
  echarts?: EChartsEngineInput
  /** 是否启用内置渲染器，默认启用；设为 `false` 后围栏回到代码块展示 */
  enabled?: boolean
  /** 图表主题，默认 `auto`（跟随最近的 `.dark` 容器与系统偏好） */
  theme?: 'light' | 'dark' | 'auto'
}

let builtinRegistered = false
let diagramTheme: 'light' | 'dark' | 'auto' = 'auto'

function ensureBuiltinRenderers(): void {
  if (builtinRegistered) return
  registerMarkdownFenceRenderer('mermaid', mermaidFenceRenderer)
  registerMarkdownFenceRenderer('echarts', echartsFenceRenderer)
  builtinRegistered = true
}

/**
 * 配置 Markdown 图表渲染。
 * 不调用也可以：围栏命中内置语言时会尝试自动解析引擎，失败则显示代码块。
 */
export function configureMarkdownDiagrams(options: MarkdownDiagramOptions = {}): void {
  if (options.theme) diagramTheme = options.theme

  if (options.enabled === false) {
    unregisterMarkdownFenceRenderer('mermaid')
    unregisterMarkdownFenceRenderer('echarts')
    return
  }

  ensureBuiltinRenderers()
  if ('mermaid' in options) setMermaidEngine(options.mermaid)
  if ('echarts' in options) setEChartsEngine(options.echarts)
}

/**
 * 解析图表主题。
 * SDK 的聊天窗口用 `.dark` 类表达深色主题，这里优先读取该类，其次跟随系统偏好。
 */
export function resolveDiagramTheme(element?: Element | null): 'light' | 'dark' {
  if (diagramTheme === 'light' || diagramTheme === 'dark') return diagramTheme
  if (element && typeof element.closest === 'function' && element.closest('.dark')) return 'dark'
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    try {
      if (window.matchMedia('(prefers-color-scheme: dark)').matches) return 'dark'
    } catch {
      return 'light'
    }
  }
  return 'light'
}

// 模块加载即注册内置渲染器，保证宿主不做任何配置时也能渲染内置语言
ensureBuiltinRenderers()
