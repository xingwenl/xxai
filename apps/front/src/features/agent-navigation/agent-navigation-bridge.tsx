import { useEffect } from 'react'
import { type AxiosRequestConfig } from 'axios'
import { useNavigate } from '@tanstack/react-router'
import {
  createAgentClient,
  type AgentClient,
  type ToolDefinition,
} from 'xxai-agent'
import 'xxai-agent/style.css'
import { useAuthStore } from '@/stores/auth-store'
import { http, type AuthResetOptOut } from '@/lib/http'
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
  displayName: string
): Promise<AgentTokenResponse> {
  const config: AxiosRequestConfig & AuthResetOptOut = {
    params: {
      display_name: displayName,
      origin: location.origin,
      host_tool_names: 'navigate_to_page',
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

    agent = createAgentClient({
      endpoint: getWebSocketEndpoint(agentId),
      platformId,
      agentId,
      getToken: async () => {
        const token = await requestAgentToken(user.name)
        return token.access_token
      },
      ui: {
        mode: 'floating',
        position: 'right',
        theme: 'auto',
        locale: 'zh-CN',
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
      pageTools: {
        enabled: true,
        confirmationKeywords: ['提交', '删除', '支付'],
        maxCalls: 500000,
        maxDurationMs: 60_000,
      },
    })
    agent.registerTool(navigationTool)

    return () => {
      active = false
      agent?.destroy()
      agent = null
    }
  }, [navigate, user])

  return null
}
