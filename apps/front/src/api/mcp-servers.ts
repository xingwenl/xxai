import { http } from '@/lib/http'

export type McpServer = {
  id: number
  platform_id: number
  name: string
  slug: string
  endpoint_url: string
  is_active: boolean
  has_auth_headers: boolean
  created_at: string
  updated_at: string
}

export type McpServerPage = {
  items: McpServer[]
  total: number
  page: number
  pageSize: number
  totalPage: number
}

export type McpServerInput = {
  name: string
  slug: string
  endpoint_url: string
  auth_headers: Record<string, string>
}

export type McpServerUpdateInput = {
  name?: string
  endpoint_url?: string
  auth_headers?: Record<string, string>
  is_active?: boolean
}

export type McpTool = {
  id: number
  server_id: number
  name: string
  description?: string | null
  input_schema: Record<string, unknown>
  is_allowed: boolean
  side_effect: 'none' | 'navigation' | 'write' | 'financial' | 'external'
}

export type McpBinding = {
  id: number
  agent_id: number
  server_id: number
  is_enabled: boolean
  created_at: string
  updated_at: string
}

export type McpAudit = {
  id: number
  platform_id: number
  agent_id: number
  user_id: number
  server_id: number
  tool_id: number
  tool_name: string
  arguments: Record<string, unknown>
  status: string
  result?: unknown
  error?: string | null
  started_at: string
  completed_at?: string | null
}

export async function listMcpServers(
  platformId: number,
  params: { page?: number; pageSize?: number } = {}
): Promise<McpServerPage> {
  const { data } = await http.get<BackendMcpServerPage>(
    `/platforms/${platformId}/mcp-servers`,
    { params: { page: params.page, page_size: params.pageSize } }
  )
  return {
    items: data?.items ?? [],
    total: Number(data?.total ?? 0),
    page: Number(data?.page_no ?? 1),
    pageSize: Number(data?.page_size ?? 20),
    totalPage: Number(data?.pages ?? 1),
  }
}

export async function createMcpServer(
  platformId: number,
  input: McpServerInput
) {
  const { data } = await http.post<McpServer>(
    `/platforms/${platformId}/mcp-servers`,
    input
  )
  return data
}

export async function updateMcpServer(
  platformId: number,
  serverId: number,
  input: McpServerUpdateInput
) {
  const { data } = await http.patch<McpServer>(
    `/platforms/${platformId}/mcp-servers/${serverId}`,
    input
  )
  return data
}

export async function deleteMcpServer(platformId: number, serverId: number) {
  await http.delete(`/platforms/${platformId}/mcp-servers/${serverId}`)
}

export async function syncMcpServerTools(platformId: number, serverId: number) {
  const { data } = await http.post<McpTool[]>(
    `/platforms/${platformId}/mcp-servers/${serverId}/sync`
  )
  return data ?? []
}

export async function listMcpServerTools(platformId: number, serverId: number) {
  const { data } = await http.get<McpTool[]>(
    `/platforms/${platformId}/mcp-servers/${serverId}/tools`
  )
  return data ?? []
}

export async function updateMcpToolPolicy(
  platformId: number,
  toolId: number,
  input: Pick<McpTool, 'is_allowed' | 'side_effect'>
) {
  const { data } = await http.patch<McpTool>(
    `/platforms/${platformId}/mcp-tools/${toolId}`,
    input
  )
  return data
}

export async function listMcpBindings(platformId: number, agentId: number) {
  const { data } = await http.get<McpBinding[]>(
    `/platforms/${platformId}/agents/${agentId}/mcp-servers`
  )
  return data ?? []
}

export async function bindMcpServer(
  platformId: number,
  agentId: number,
  serverId: number
) {
  await http.put(`/platforms/${platformId}/agents/${agentId}/mcp-servers`, {
    server_id: serverId,
  })
}

export async function unbindMcpServer(
  platformId: number,
  agentId: number,
  serverId: number
) {
  await http.delete(
    `/platforms/${platformId}/agents/${agentId}/mcp-servers/${serverId}`
  )
}

export async function listMcpAudits(platformId: number) {
  const { data } = await http.get<McpAudit[]>(
    `/platforms/${platformId}/mcp-audits`
  )
  return data ?? []
}

type BackendMcpServerPage = {
  page_no: number
  page_size: number
  items: McpServer[]
  total: number
  pages: number
}
