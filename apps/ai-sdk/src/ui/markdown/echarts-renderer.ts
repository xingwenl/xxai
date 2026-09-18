// 内置 ECharts 渲染器。
// 与 Mermaid 相同的引擎解析策略（显式注入 → 全局变量 → 动态 import），
// 但只接受 JSON 配置：不使用 eval / new Function，避免执行模型输出里的任意代码。

import {
  MAX_DIAGRAM_SOURCE_LENGTH,
  createMarkdownFenceError,
  type MarkdownFenceRenderer
} from './fence-registry'

export interface EChartsInstanceLike {
  setOption(option: unknown): void
  resize(): void
  dispose(): void
}

/** ECharts 的最小接口定义：SDK 不依赖 echarts 包及其类型声明 */
export interface EChartsLike {
  init(element: HTMLElement, theme?: string): EChartsInstanceLike
}

let injectedEngine: EChartsLike | null | undefined
let enginePromise: Promise<EChartsLike | null> | null = null

/** 显式注入引擎实例；传 `null` 表示明确禁用，`undefined` 表示恢复自动解析 */
export function setEChartsEngine(engine: EChartsLike | null | undefined): void {
  injectedEngine = engine
  enginePromise = null
}

/**
 * 在不执行任何 JS 的前提下做两处保守归一化，兼容模型常见的 JSON 书写习惯：
 * 1. 去掉字符串字面量之外的 `//` 与 `/* *\/` 注释
 * 2. 去掉对象/数组结尾的多余逗号
 * 单引号、无引号键名、函数值等仍然拒绝，保证不会执行模型输出里的代码。
 */
function normalizeJsonText(text: string): string {
  let result = ''
  let inString = false
  let inLineComment = false
  let inBlockComment = false

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]
    const next = text[index + 1]

    if (inLineComment) {
      if (char === '\n') {
        inLineComment = false
        result += char
      }
      continue
    }
    if (inBlockComment) {
      if (char === '*' && next === '/') {
        inBlockComment = false
        index += 1
      }
      continue
    }
    if (inString) {
      result += char
      if (char === '\\') {
        result += next ?? ''
        index += 1
        continue
      }
      if (char === '"') inString = false
      continue
    }
    if (char === '"') {
      inString = true
      result += char
      continue
    }
    if (char === '/' && next === '/') {
      inLineComment = true
      index += 1
      continue
    }
    if (char === '/' && next === '*') {
      inBlockComment = true
      index += 1
      continue
    }
    if (char === ',') {
      let lookahead = index + 1
      while (lookahead < text.length && /\s/.test(text[lookahead])) lookahead += 1
      // 逗号后面直接是 } 或 ]，属于模型常见的尾随逗号，直接丢弃
      if (text[lookahead] === '}' || text[lookahead] === ']') continue
    }
    result += char
  }

  return result
}

/**
 * 解析围栏内容为 ECharts 配置。
 * 只接受 JSON 对象：数组、标量、JS 表达式、语法错误一律视为不可渲染。
 */
export function parseEChartsOption(code: string): Record<string, unknown> | null {
  const text = String(code || '').trim()
  if (!text || text.length > MAX_DIAGRAM_SOURCE_LENGTH) return null
  const parsed = tryParseJson(text) ?? tryParseJson(normalizeJsonText(text))
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
  return parsed as Record<string, unknown>
}

function tryParseJson(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

async function resolveECharts(): Promise<EChartsLike | null> {
  if (injectedEngine !== undefined) return injectedEngine

  const globalEngine = (globalThis as { echarts?: EChartsLike }).echarts
  if (globalEngine && typeof globalEngine.init === 'function') {
    enginePromise = null
    return globalEngine
  }

  if (!enginePromise) {
    const specifier = 'echarts'
    enginePromise = import(/* @vite-ignore */ specifier)
      .then((module) => ((module as { default?: EChartsLike }).default || (module as EChartsLike)))
      .catch(() => null)
  }
  const resolved = await enginePromise
  // 解析失败不长期缓存：宿主可能在页面加载后才引入脚本，后续消息需要能重试成功
  if (!resolved) enginePromise = null
  return resolved
}

export const echartsFenceRenderer: MarkdownFenceRenderer = {
  language: 'echarts',
  async mount(element, code, context) {
    const option = parseEChartsOption(code)
    if (!option) throw createMarkdownFenceError('option-invalid', 'echarts option must be a JSON object')

    const engine = await resolveECharts()
    if (!engine) throw createMarkdownFenceError('engine-missing', 'echarts engine is not available')

    // ECharts 需要容器具备显式高度，否则初始化时拿不到尺寸而报错
    if (!element.style.minHeight) element.style.minHeight = '320px'
    const chart = engine.init(element, context.theme === 'dark' ? 'dark' : undefined)
    chart.setOption(option)

    // 容器宽度变化（窗口缩放、侧栏开合）后需要主动 resize，否则画布会变形
    let disposed = false
    let observer: ResizeObserver | null = null
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => {
        if (!disposed) chart.resize()
      })
      observer.observe(element)
    }

    return () => {
      disposed = true
      observer?.disconnect()
      chart.dispose()
    }
  }
}
