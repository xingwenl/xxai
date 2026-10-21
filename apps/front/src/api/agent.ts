import { http } from '@/lib/http'

export type Agent = {
  id: number
  platform_id: number
  name: string
  slug: string
  description?: string | null
  is_default: boolean
  is_active: boolean
  default_version_id?: number | null
  /**
   * 绑定的编排工作流 id；null = 未绑定。
   * 绑定后该 Agent 的会话可以按这条工作流编排执行，工作流必须属于同一平台且处于 active。
   */
  orchestration_workflow_id?: number | null
  created_at?: string
  updated_at?: string
}

export type AgentPage = {
  items: Agent[]
  total: number
  page: number
  pageSize: number
  totalPage: number
}

export type AgentInput = {
  name: string
  slug: string
  description?: string
}

export type AgentUpdateInput = AgentInput & {
  is_active: boolean
  /**
   * 编排绑定：显式传 null 表示解绑，整个字段不传表示不改动。
   * 因此更新时务必显式带上当前选择值，别用 undefined 表达「清空」。
   */
  orchestration_workflow_id?: number | null
}

export type AgentVersion = {
  id: number
  agent_id: number
  version: number
  system_prompt: string
  temperature: number
  model_options: Record<string, unknown>
  created_at: string
  published_at?: string | null
}

export type AgentDetail = Agent & {
  current_version: AgentVersion | null
}

export type AgentVersionInput = {
  system_prompt: string
  temperature: number
  model_options: Record<string, unknown>
  capabilities?: Record<string, unknown> | null
}

export async function listAgents(
  platformId: number,
  params: { page?: number; pageSize?: number } = {}
): Promise<AgentPage> {
  const { data } = await http.get<BackendAgentPage>(
    `/platforms/${platformId}/agents`,
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

export async function getAgent(
  platformId: number,
  agentId: number
): Promise<AgentDetail> {
  const { data } = await http.get<AgentDetail>(
    `/platforms/${platformId}/agents/${agentId}`
  )
  return data
}

export async function createAgent(
  platformId: number,
  input: AgentInput
): Promise<Agent> {
  const { data } = await http.post<Agent>(
    `/platforms/${platformId}/agents`,
    input
  )
  return data
}

export async function updateAgent(
  platformId: number,
  agentId: number,
  input: AgentUpdateInput
): Promise<Agent> {
  const { data } = await http.patch<Agent>(
    `/platforms/${platformId}/agents/${agentId}`,
    input
  )
  return data
}

export async function deleteAgent(platformId: number, agentId: number) {
  await http.delete(`/platforms/${platformId}/agents/${agentId}`)
}

export async function listAgentVersions(
  platformId: number,
  agentId: number
): Promise<AgentVersion[]> {
  const { data } = await http.get<AgentVersion[]>(
    `/platforms/${platformId}/agents/${agentId}/versions`
  )
  return data ?? []
}

export async function createAgentVersion(
  platformId: number,
  agentId: number,
  input: AgentVersionInput
): Promise<AgentVersion> {
  const { data } = await http.post<AgentVersion>(
    `/platforms/${platformId}/agents/${agentId}/versions`,
    input
  )
  return data
}

export async function publishAgentVersion(
  platformId: number,
  agentId: number,
  versionId: number
): Promise<AgentVersion> {
  const { data } = await http.post<AgentVersion>(
    `/platforms/${platformId}/agents/${agentId}/versions/${versionId}/publish`
  )
  return data
}

export async function rollbackAgentVersion(
  platformId: number,
  agentId: number,
  versionId: number
): Promise<AgentVersion> {
  const { data } = await http.post<AgentVersion>(
    `/platforms/${platformId}/agents/${agentId}/versions/${versionId}/rollback`
  )
  return data
}

/**
 * 主智能体的一条「可派子智能体」绑定。
 * 字段沿用后端 snake_case 契约，顺序即列表展示与运行期提示顺序。
 */
export type AgentSubagent = {
  child_agent_id: number
  slug: string
  name: string
  description?: string | null
  enabled: boolean
  sort_order: number
  /** 子 Agent 是否有已发布版本；未发布时运行期委派会失败。 */
  published: boolean
  /** 子 Agent 是否启用；停用后不可被派发。 */
  active: boolean
}

/** 可新增为子智能体的候选：本平台已发布、且尚未在当前绑定里的 Agent。 */
export type AgentSubagentCandidate = {
  id: number
  slug: string
  name: string
  description?: string | null
}

export type AgentSubagentListData = {
  items: AgentSubagent[]
  /** true 表示没有任何绑定，运行期回退「全平台已发布智能体（排除自己）」 */
  fallback: boolean
  available: AgentSubagentCandidate[]
}

/** 整表替换时的单项：数组顺序即 sort_order。 */
export type AgentSubagentUpdateItem = {
  child_agent_id: number
  enabled: boolean
}

export async function listAgentSubagents(
  platformId: number,
  agentId: number
): Promise<AgentSubagentListData> {
  const { data } = await http.get<AgentSubagentListData>(
    `/platforms/${platformId}/agents/${agentId}/subagents`
  )
  return data ?? { items: [], fallback: true, available: [] }
}

export async function replaceAgentSubagents(
  platformId: number,
  agentId: number,
  items: AgentSubagentUpdateItem[]
): Promise<AgentSubagentListData> {
  const { data } = await http.put<AgentSubagentListData>(
    `/platforms/${platformId}/agents/${agentId}/subagents`,
    { items }
  )
  return data ?? { items: [], fallback: true, available: [] }
}

type BackendAgentPage = {
  page_no: number
  page_size: number
  items: Agent[]
  total: number
  pages: number
}
