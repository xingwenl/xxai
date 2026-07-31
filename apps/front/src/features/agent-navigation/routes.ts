export const internalPageRoutes = {
  聊天: '/chats',
  智能体管理: '/ai/bots',
  平台管理: '/ai/platforms',
  知识库管理: '/ai/knowledge-bases',
  技能管理: '/ai/skills',
  EmbedClient管理: '/ai/embed-clients',
  宿主工具策略: '/ai/host-tools',
  模型用量: '/ai/model-usage',
  人员管理: '/system/users',
  角色管理: '/system/roles',
  AIHTML列表: '/system/ai-html-pages',
  MCP服务管理: '/system/mcp-servers',
} as const

export type InternalPageRoute =
  (typeof internalPageRoutes)[keyof typeof internalPageRoutes]

export function resolveInternalRoute(
  pageName: string
): InternalPageRoute | null {
  const normalized = pageName.trim().replace(/[\s_-]+/g, '')
  const entry = Object.entries(internalPageRoutes).find(
    ([name]) => name.replace(/[\s_-]+/g, '') === normalized
  )
  return entry?.[1] ?? null
}
