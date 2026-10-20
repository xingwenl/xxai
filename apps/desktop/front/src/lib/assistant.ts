// 全局助手：宿主壳层单例挂载 ai-sdk 悬浮窗，并把子应用注册的方法同步成宿主工具。
//
// 为什么是单例：floating 面板会挂到 document.body，重复 createAgentClient 会叠加多个
// 悬浮球；而且 destroy() 不会卸载内部 Vue 应用（会泄漏）。宿主壳层只创建一次，
// 工具集合随子应用的 desktop.tools.register/unregister 动态增减。

import { createAgentClient, type AgentClient, type ToolDefinition } from 'xxai-agent'
import 'xxai-agent/style.css'
import { getAgentConfig, issueAgentToken, type AgentConfig } from './api'
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
    if (!config.enabled) {
      console.info('[assistant] 未配置智能体后端，跳过挂载：', config.reason ?? '')
      return
    }
    // remote 模式：先换一张短期 token 拿到真实 WS 地址与平台标识；后续 SDK 刷新 token 也走宿主，
    // 这样 client_secret 只存在于宿主进程，渲染层拿到的永远是短期凭证。
    let endpoint = config.endpoint
    let platformId = config.platformId
    let agentId = config.agentId
    let displayName = config.displayName || '桌面用户'
    let getToken: () => Promise<string>
    if (config.mode === 'remote') {
      try {
        const initial = await issueAgentToken(window.location.origin)
        endpoint = initial.endpoint
        platformId = initial.platformId
        agentId = String(initial.agentId)
        displayName = initial.displayName || displayName
      } catch (err) {
        console.warn('[assistant] 换发 AI Base token 失败，请检查设置页的智能体后端配置', err)
        return
      }
      getToken = async () => (await issueAgentToken(window.location.origin)).token
    } else {
      if (!endpoint || !agentId || !platformId) {
        console.info('[assistant] 本地网关参数不完整，跳过挂载')
        return
      }
      const devToken = config.token || ''
      getToken = async () => devToken
    }
    const agent: AgentClient = createAgentClient({
      endpoint: resolveEndpoint(String(endpoint)),
      platformId: String(platformId),
      agentId: String(agentId),
      getToken,
      user: { id: 'desktop-user', displayName },
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
      console.warn('[assistant] 连接失败（本地网关请检查 DESKTOP_DEV_AGENT，AI Base 请检查配置与网络）', err)
    }
  })()
  return mounting
}

/** 取消方法集合订阅（宿主壳层卸载时调用；当前壳层常驻，一般不触发）。 */
export function detachAssistantBridge(): void {
  unsubscribeBridge?.()
  unsubscribeBridge = null
}
