// 全局助手：宿主壳层单例挂载 ai-sdk 悬浮窗，并把子应用注册的方法同步成宿主工具。
//
// 为什么是单例：floating 面板会挂到 document.body，重复 createAgentClient 会叠加多个
// 悬浮球；而且 destroy() 不会卸载内部 Vue 应用（会泄漏）。宿主壳层只创建一次，
// 工具集合随子应用的 desktop.tools.register/unregister 动态增减。

import { createAgentClient, type AgentClient, type ToolDefinition } from 'xxai-agent'
import 'xxai-agent/style.css'
import { getAgentConfig, type AgentConfig } from './api'
import { listBridgeTools, subscribeBridgeTools, toAgentTool } from './tool-bridge'

let client: AgentClient | null = null
let unsubscribeBridge: (() => void) | null = null
let mounting: Promise<void> | null = null

/** 相对 endpoint 还原成当前页面的绝对 ws 地址（SDK 要求 WebSocket 协议地址）。 */
function resolveEndpoint(endpoint: string): string {
  if (/^wss?:\/\//i.test(endpoint)) return endpoint
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const path = endpoint.startsWith('/') ? endpoint : `/${endpoint}`
  return `${scheme}://${window.location.host}${path}`
}

/** 把当前方法集合同步给助手：注销已消失的，再注册现存全部（覆盖 schema 变更）。 */
function syncTools(agent: AgentClient): void {
  const tools = listBridgeTools()
  const names = new Set(tools.map((tool) => tool.name))
  for (const existing of agent.getToolNames()) {
    if (!names.has(existing)) agent.unregisterTool(existing)
  }
  if (tools.length) {
    agent.registerTools(tools.map((tool) => toAgentTool(tool) as ToolDefinition))
  }
}

/** 挂载全局助手；未配置智能体后端时静默跳过。重复调用安全。 */
export function mountAssistant(): Promise<void> {
  if (client) return Promise.resolve()
  if (mounting) return mounting
  mounting = (async () => {
    let config: AgentConfig
    try {
      config = await getAgentConfig()
    } catch (err) {
      console.warn('[assistant] 读取智能体配置失败', err)
      return
    }
    if (!config.enabled || !config.endpoint || !config.agentId || !config.platformId) {
      console.info('[assistant] 未配置智能体后端，跳过挂载：', config.reason ?? '')
      return
    }
    const agent: AgentClient = createAgentClient({
      endpoint: resolveEndpoint(config.endpoint),
      platformId: config.platformId,
      agentId: config.agentId,
      getToken: async () => config.token || '',
      user: { id: 'desktop-user', displayName: '桌面用户' },
      ui: { mode: 'floating', position: 'right', theme: 'auto' },
    })
    client = agent
    // 先同步已有方法，再订阅后续变化：子应用打开顺序不影响助手能看到的工具集合
    syncTools(agent)
    unsubscribeBridge = subscribeBridgeTools(() => syncTools(agent))
    agent.on('error', (err) => console.warn('[assistant] 连接错误', err))
    try {
      await agent.connect()
    } catch (err) {
      console.warn('[assistant] 连接失败（检查 DESKTOP_DEV_AGENT 是否开启）', err)
    }
  })()
  return mounting
}

/** 取消方法集合订阅（宿主壳层卸载时调用；当前壳层常驻，一般不触发）。 */
export function detachAssistantBridge(): void {
  unsubscribeBridge?.()
  unsubscribeBridge = null
}
