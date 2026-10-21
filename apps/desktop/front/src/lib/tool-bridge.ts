// 子应用方法桥：把 iframe 里注册的桌面方法汇总成宿主工具，供全局助手动态挂载。
//
// 子应用通过 desktop.tools.register 声明「名字 + JSON Schema + 执行函数」，
// 宿主壳层的全局助手再把它们注册给 ai-sdk。子应用切页后 iframe 常驻（隐藏），
// 因此方法不会因为用户离开子应用而消失；同名方法重注册会覆盖旧实现。

import { logPluginEvent, type Plugin } from './api'

export type HostToolSideEffect = 'none' | 'navigation' | 'write' | 'financial' | 'external'

/** 子应用声明的方法定义，字段与 ai-sdk 的 ToolDefinition 对齐。 */
export interface HostToolDefinition {
  name: string
  description: string
  inputSchema: Record<string, unknown>
  sideEffect?: HostToolSideEffect
}

/** 方法执行函数；入参已按 inputSchema 由 SDK 做过浅校验。 */
export type HostToolHandler = (args: unknown) => unknown | Promise<unknown>

export interface BridgeTool extends HostToolDefinition {
  pluginId: string
  pluginName: string
  execute: HostToolHandler
}

const tools = new Map<string, BridgeTool>()
const listeners = new Set<() => void>()

function notify(): void {
  for (const listener of listeners) {
    try {
      listener()
    } catch (err) {
      console.error('[tool-bridge] 监听器异常', err)
    }
  }
}

/** 上报方法注册结果；日志接口失败不影响注册本身（插件可能已停用）。 */
function report(pluginId: string, event: string, detail: string): void {
  void logPluginEvent(pluginId, event, detail).catch(() => {})
}

/** 注册某子应用的方法；方法名跨子应用冲突时保留先注册者并告警。 */
export function registerPluginTools(
  plugin: Plugin,
  defs: HostToolDefinition[],
  handlers: Record<string, HostToolHandler>,
): void {
  let changed = false
  const registered: string[] = []
  const skipped: string[] = []
  for (const def of defs) {
    const handler = handlers[def.name]
    if (typeof handler !== 'function') {
      console.warn(`[tool-bridge] ${plugin.id} 的方法 ${def.name} 缺少执行函数，已跳过`)
      skipped.push(def.name)
      continue
    }
    const existing = tools.get(def.name)
    if (existing && existing.pluginId !== plugin.id) {
      console.warn(`[tool-bridge] 方法名 ${def.name} 已被 ${existing.pluginId} 占用，${plugin.id} 的注册被忽略`)
      skipped.push(`${def.name}(与 ${existing.pluginId} 冲突)`)
      continue
    }
    tools.set(def.name, { ...def, pluginId: plugin.id, pluginName: plugin.name, execute: handler })
    registered.push(def.name)
    changed = true
  }
  if (registered.length > 0) {
    report(plugin.id, 'tools_registered', registered.join(','))
  }
  if (skipped.length > 0) {
    report(plugin.id, 'tool_skipped', skipped.join(','))
  }
  if (changed) notify()
}

/** 移除某子应用注册的方法；只删属于该子应用的同名条目。 */
export function unregisterPluginTools(pluginId: string, names: string[]): void {
  let changed = false
  for (const name of names) {
    const existing = tools.get(name)
    if (!existing || existing.pluginId !== pluginId) continue
    tools.delete(name)
    changed = true
  }
  if (changed) notify()
}

/** 移除某子应用注册的全部方法（子应用被禁用/卸载时调用）。 */
export function clearPluginTools(pluginId: string): void {
  let changed = false
  for (const [name, tool] of tools) {
    if (tool.pluginId !== pluginId) continue
    tools.delete(name)
    changed = true
  }
  if (changed) notify()
}

/** 当前所有可挂给助手的方法快照。 */
export function listBridgeTools(): BridgeTool[] {
  return [...tools.values()]
}

/** 某子应用当前已注册的方法数（设置页展示运行态用）。 */
export function countPluginTools(pluginId: string): number {
  let count = 0
  for (const tool of tools.values()) {
    if (tool.pluginId === pluginId) count += 1
  }
  return count
}

/** 订阅方法集合变化（返回取消订阅函数）。 */
export function subscribeBridgeTools(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** 转成 ai-sdk 的 ToolDefinition；执行异常统一包成中文错误，便于模型向用户复述原因。 */
export function toAgentTool(tool: BridgeTool) {
  return {
    name: tool.name,
    description: tool.description,
    inputSchema: tool.inputSchema,
    sideEffect: tool.sideEffect,
    execute: async (params: unknown) => {
      try {
        return await tool.execute(params)
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        throw new Error(`${tool.pluginName}执行 ${tool.name} 失败：${message}`)
      }
    },
  }
}
