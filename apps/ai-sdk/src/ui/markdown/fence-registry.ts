// Markdown 围栏渲染器的统一接缝。
// 消息里的 ```lang 围栏命中已注册渲染器时交给渲染器绘制（图表、自定义可视化等）；
// 未注册语言保持 markdown-it 默认的代码块行为，保证任何场景下内容都可见、可复制。

/** 单个图表源码长度上限，避免超长输入拖慢渲染或卡住页面 */
export const MAX_DIAGRAM_SOURCE_LENGTH = 20000

export interface MarkdownFenceContext {
  /** 已解析出的目标主题，供渲染器选择配色 */
  theme: 'light' | 'dark'
  /** 归一化后的语言名（小写、去空格） */
  language: string
}

export type MarkdownFenceCleanup = () => void

export interface MarkdownFenceRenderer {
  language: string
  /**
   * 把围栏源码渲染到指定容器。
   * 可同步或异步返回清理函数；抛错或返回前组件已卸载时，宿主组件降级为代码块。
   */
  mount(
    element: HTMLElement,
    code: string,
    context: MarkdownFenceContext
  ): MarkdownFenceCleanup | void | Promise<MarkdownFenceCleanup | void>
}

export type MarkdownFenceRendererInput = Omit<MarkdownFenceRenderer, 'language'> & { language?: string }

/**
 * 降级原因码。
 * 渲染器失败时带上原因，宿主组件才能给出可诊断的提示，而不是笼统的“渲染失败”。
 */
export type MarkdownFenceErrorCode = 'engine-missing' | 'source-not-ready' | 'option-invalid'

export function createMarkdownFenceError(
  code: MarkdownFenceErrorCode,
  message: string
): Error & { code: MarkdownFenceErrorCode } {
  const error = new Error(message) as Error & { code: MarkdownFenceErrorCode }
  error.code = code
  return error
}

export function getMarkdownFenceErrorCode(error: unknown): MarkdownFenceErrorCode | null {
  const code = (error as { code?: unknown } | null)?.code
  return code === 'engine-missing' || code === 'source-not-ready' || code === 'option-invalid' ? code : null
}

const renderers = new Map<string, MarkdownFenceRenderer>()

/** 围栏语言按小写归一化，`Mermaid` / `MERMAID` / `mermaid` 视为同一个渲染器 */
export function normalizeFenceLanguage(language: string): string {
  return String(language || '').trim().toLowerCase()
}

export function registerMarkdownFenceRenderer(language: string, renderer: MarkdownFenceRendererInput): void {
  const normalized = normalizeFenceLanguage(language)
  if (!normalized || typeof renderer?.mount !== 'function') return
  renderers.set(normalized, { ...renderer, language: normalized })
}

export function unregisterMarkdownFenceRenderer(language: string): void {
  renderers.delete(normalizeFenceLanguage(language))
}

export function getMarkdownFenceRenderer(language: string): MarkdownFenceRenderer | undefined {
  const normalized = normalizeFenceLanguage(language)
  return normalized ? renderers.get(normalized) : undefined
}

export function listMarkdownFenceLanguages(): string[] {
  return Array.from(renderers.keys()).sort()
}
