import { http } from '@/lib/http'

export type HostToolSideEffect =
  | 'none'
  | 'navigation'
  | 'write'
  | 'financial'
  | 'external'

export type HostToolConfirmationPolicy = 'auto' | 'always'

export type HostToolPolicy = {
  id: number
  platform_id: number
  name: string
  description: string
  input_schema: Record<string, unknown>
  output_schema?: Record<string, unknown> | null
  side_effect: HostToolSideEffect
  confirmation_policy: HostToolConfirmationPolicy
  is_enabled: boolean
}

export type HostToolPolicyInput = {
  name: string
  description: string
  input_schema: Record<string, unknown>
  output_schema?: Record<string, unknown> | null
  side_effect: HostToolSideEffect
  confirmation_policy: HostToolConfirmationPolicy
}

export type HostToolPolicyUpdateInput = Omit<HostToolPolicyInput, 'name'> & {
  is_enabled: boolean
}

export type AgentHostToolBinding = {
  id: number
  agent_id: number
  tool_id: number
  is_enabled: boolean
}

export type EmbedClientHostToolBinding = {
  id: number
  client_id: number
  tool_id: number
}

export type HostToolAudit = {
  id: number
  call_id: string
  platform_id: number
  agent_id: number
  platform_end_user_id: number
  conversation_id?: number | null
  request_id?: string | null
  tool_name: string
  status: string
  arguments: Record<string, unknown>
  result?: unknown
  error?: string | null
}

export async function listHostTools(platformId: number) {
  const { data } = await http.get<HostToolPolicy[]>(
    `/platforms/${platformId}/host-tools`
  )
  return data ?? []
}

export async function createHostTool(
  platformId: number,
  input: HostToolPolicyInput
) {
  const { data } = await http.post<HostToolPolicy>(
    `/platforms/${platformId}/host-tools`,
    input
  )
  return data
}

export async function updateHostTool(
  platformId: number,
  toolId: number,
  input: HostToolPolicyUpdateInput
) {
  const { data } = await http.patch<HostToolPolicy>(
    `/platforms/${platformId}/host-tools/${toolId}`,
    input
  )
  return data
}

export async function listAgentHostTools(platformId: number, agentId: number) {
  const { data } = await http.get<AgentHostToolBinding[]>(
    `/platforms/${platformId}/agents/${agentId}/host-tools`
  )
  return data ?? []
}

export async function bindAgentHostTool(
  platformId: number,
  agentId: number,
  toolId: number
) {
  await http.put(
    `/platforms/${platformId}/agents/${agentId}/host-tools/${toolId}`
  )
}

export async function unbindAgentHostTool(
  platformId: number,
  agentId: number,
  toolId: number
) {
  await http.delete(
    `/platforms/${platformId}/agents/${agentId}/host-tools/${toolId}`
  )
}

export async function listEmbedClientHostTools(
  platformId: number,
  clientId: string
) {
  const { data } = await http.get<EmbedClientHostToolBinding[]>(
    `/platforms/${platformId}/embed-clients/${clientId}/host-tools`
  )
  return data ?? []
}

export async function bindEmbedClientHostTool(
  platformId: number,
  clientId: string,
  toolId: number
) {
  await http.put(
    `/platforms/${platformId}/embed-clients/${clientId}/host-tools/${toolId}`
  )
}

export async function unbindEmbedClientHostTool(
  platformId: number,
  clientId: string,
  toolId: number
) {
  await http.delete(
    `/platforms/${platformId}/embed-clients/${clientId}/host-tools/${toolId}`
  )
}

export async function listHostToolAudits(platformId: number) {
  const { data } = await http.get<HostToolAudit[]>(
    `/platforms/${platformId}/host-tool-audits`
  )
  return data ?? []
}
