import { http } from '@/lib/http'

export type BuiltinToolSideEffect = 'none'

export type AgentBuiltinTool = {
  name: string
  description: string
  input_schema: Record<string, unknown>
  side_effect: BuiltinToolSideEffect
  is_enabled: boolean
}

export async function listAgentBuiltinTools(
  platformId: number,
  agentId: number
) {
  const { data } = await http.get<AgentBuiltinTool[]>(
    `/platforms/${platformId}/agents/${agentId}/builtin-tools`
  )
  return data ?? []
}

export async function updateAgentBuiltinTool(
  platformId: number,
  agentId: number,
  toolName: string,
  isEnabled: boolean
) {
  const { data } = await http.put<AgentBuiltinTool>(
    `/platforms/${platformId}/agents/${agentId}/builtin-tools/${encodeURIComponent(toolName)}`,
    { is_enabled: isEnabled }
  )
  return data
}
