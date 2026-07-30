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
}

export type AgentVersion = {
  id: number
  agent_id: number
  version: number
  system_prompt: string
  model_name: string
  model_base_url?: string | null
  temperature: number
  model_options: Record<string, unknown>
  created_at: string
  published_at?: string | null
  has_api_key: boolean
}

export type AgentVersionInput = {
  system_prompt: string
  model_name: string
  model_base_url?: string
  api_key?: string
  temperature: number
  model_options: Record<string, unknown>
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

type BackendAgentPage = {
  page_no: number
  page_size: number
  items: Agent[]
  total: number
  pages: number
}
