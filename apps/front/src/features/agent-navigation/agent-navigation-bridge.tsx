import { useEffect } from 'react'
import { type AxiosRequestConfig } from 'axios'
import { useNavigate } from '@tanstack/react-router'
import {
  createAgentClient,
  type AgentClient,
  type AgentSwitchOption,
  type ToolDefinition,
} from 'xxai-agent'
import 'xxai-agent/style.css'
import { listAgents } from '@/api/agent'
import { listEmbedClientAgents } from '@/api/embed-clients'
import { useAuthStore } from '@/stores/auth-store'
import { http, type AuthResetOptOut } from '@/lib/http'
import { readEmbedTokenClientId } from './embed-token'
import { resolveInternalRoute } from './routes'

type AgentTokenResponse = {
  access_token: string
  expires_in: number
}

type NavigationToolInput = {
  page_name?: unknown
}

function getWebSocketEndpoint(agentId: string): string {
  const configured = import.meta.env.VITE_AGENT_WS_URL as string | undefined
  if (configured) return configured.replace(/\/$/, '')

  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${location.host}/api/v1/ws/agents/${agentId}`
}

async function requestAgentToken(
  displayName: string,
  agentId?: string
): Promise<AgentTokenResponse> {
  const config: AxiosRequestConfig & AuthResetOptOut = {
    params: {
      display_name: displayName,
      origin: location.origin,
      host_tool_names: 'navigate_to_page',
      // 切换智能体后 SDK 会用目标 agentId 重新换 token；服务端仍按 Client 绑定校验，
      // 这里只负责把目标 id 透传过去。
      agent_id: agentId,
    },
    // 悬浮 Agent 是可选能力：Embed Client 来源白名单没覆盖当前后台地址时这里会 401，
    // 但用户的后台登录态仍然有效，不能因为旁路能力失败把人踢回登录页。
    skipAuthReset: true,
  }
  const { data } = await http.get<AgentTokenResponse>(
    '/embed/agent-token',
    config
  )
  return data
}

/**
 * 解析当前悬浮助手使用的 Embed Client。
 *
 * 优先用显式配置的 `VITE_AGENT_CLIENT_ID`（一个部署同时接多个 Client 时使用）；
 * 没配置时从后端签发的 Embed token 载荷里读取 `client_id`——后端就是用它签发 token 的，
 * 这样宿主不必重复维护一份 client_id，也不会因为漏配导致切换入口静默消失。
 *
 * 换签失败（例如当前后台来源不在 Client 白名单）时返回 undefined：切换能力关闭，
 * 悬浮助手本身仍然按原有路径挂载并暴露错误，保持旁路能力失败不影响主壳。
 */
async function resolveEmbedClientId(
  displayName: string,
  agentId: string
): Promise<string | undefined> {
  const configured = (
    import.meta.env.VITE_AGENT_CLIENT_ID as string | undefined
  )?.trim()
  if (configured) return configured

  try {
    const token = await requestAgentToken(displayName, agentId)
    return readEmbedTokenClientId(token.access_token)
  } catch (error) {
    if (import.meta.env.DEV) {
      console.warn(
        '[agent-navigation] 无法解析 Embed Client，已关闭悬浮助手的智能体切换',
        error
      )
    }
    return undefined
  }
}

/**
 * 拉取「后台已启用且当前 Embed Client 已绑定」的智能体，作为 SDK 切换候选。
 *
 * 列表接口需要后台登录态，因此由宿主（而不是 SDK）拉取并传入；拿不到 Client
 * 或拉取失败时直接关闭切换入口（fail closed），不影响悬浮助手本身的挂载。
 * 设计见 docs/adr/0014-host-provided-agent-switching.md。
 */
async function loadAgentSwitchOptions(
  platformId: string,
  clientId: string | undefined
): Promise<AgentSwitchOption[] | undefined> {
  if (!clientId) {
    if (import.meta.env.DEV) {
      console.warn(
        '[agent-navigation] 未解析到 Embed Client，已关闭悬浮助手的智能体切换'
      )
    }
    return undefined
  }
  try {
    const [agents, bindings] = await Promise.all([
      listAgents(Number(platformId), { page: 1, pageSize: 100 }),
      listEmbedClientAgents(Number(platformId), clientId),
    ])
    const boundIds = new Set(bindings.map((binding) => binding.agent_id))
    const options = agents.items
      .filter((agent) => agent.is_active && boundIds.has(agent.id))
      .map((agent) => ({
        agentId: String(agent.id),
        name: agent.name,
        slug: agent.slug,
        description: agent.description ?? null,
      }))
    // 只有一个候选时展示切换器没有意义，交给 SDK 的空列表退化逻辑。
    return options.length > 1 ? options : undefined
  } catch (error) {
    // 拉列表失败不能让整个悬浮助手不可用：降级为不展示切换入口。
    console.warn(
      '[agent-navigation] 加载可切换智能体失败，已关闭切换入口',
      error
    )
    return undefined
  }
}

export function AgentNavigationBridge() {
  // return null
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.auth.user)

  useEffect(() => {
    if (!user) return

    const platformId = String(import.meta.env.VITE_AGENT_PLATFORM_ID ?? '1')
    const agentId = String(import.meta.env.VITE_AGENT_ID ?? '1')
    let active = true
    let agent: AgentClient | null = null

    const navigationTool: ToolDefinition = {
      name: 'navigate_to_page',
      description: '打开后台已有页面。page_name 必须是后台页面中文名称。',
      inputSchema: {
        type: 'object',
        properties: {
          page_name: {
            type: 'string',
            description: '页面名称，例如“智能体管理”或“模型用量”',
          },
        },
        required: ['page_name'],
        additionalProperties: false,
      },
      sideEffect: 'navigation',
      async execute(params) {
        const pageName = (params as NavigationToolInput)?.page_name
        if (typeof pageName !== 'string') {
          throw new Error('page_name must be a string')
        }

        const route = resolveInternalRoute(pageName)
        if (!route) {
          throw new Error(`不支持打开页面：${pageName}`)
        }
        if (!active) throw new Error('navigation tool is unavailable')

        await navigate({ to: route })
        return { opened: true, page_name: pageName, route }
      },
    }

    void (async () => {
      // 先确定当前 Client，再据此取候选智能体；两步都做了降级，
      // 任何一步失败都只关闭切换入口，不阻断悬浮助手挂载。
      const clientId = await resolveEmbedClientId(user.name, agentId)
      if (!active) return
      const switchOptions = await loadAgentSwitchOptions(platformId, clientId)
      if (!active) return

      agent = createAgentClient({
        endpoint: getWebSocketEndpoint(agentId),
        platformId,
        agentId,
        agentSwitching: switchOptions ? { agents: switchOptions } : undefined,
        getToken: async (ctx) => {
          const token = await requestAgentToken(user.name, ctx.agentId)
          return token.access_token
        },
        ui: {
          mode: 'floating',
          position: 'right',
          theme: 'auto',
          locale: 'zh-CN',
          layout: 'desktop',
          showAgentSteps: true,
        },
        systemPrompt:
          '你是后台管理助手。根据用户意图使用当前 Agent 已授权的工具；涉及页面导航时使用 navigate_to_page 和页面中文名称，不要编造工具结果。',
        callbacks: {
          onError: (error) => {
            // SDK errors should not prevent the authenticated shell from rendering.
            // eslint-disable-next-line no-console
            if (import.meta.env.DEV) console.warn('[agent-navigation]', error)
          },
        },
        thinking: true,
        pageTools: {
          enabled: true,
          confirmationKeywords: ['提交', '删除', '支付'],
          maxCalls: 500000,
          maxDurationMs: 600_000,
        },
      })
      if (!active) {
        agent.destroy()
        agent = null
        return
      }
      agent.registerTool(navigationTool)
    })()

    return () => {
      active = false
      agent?.destroy()
      agent = null
    }
  }, [navigate, user])

  return null
}
