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

/** 工具组目录（只读）：组与成员关系由后端常量与工具声明决定。 */
export type ToolGroup = {
  group: string
  title: string
  description: string
  eager: boolean
  tool_names: string[]
}

export type ToolGroupCatalog = {
  builtin: ToolGroup[]
  host: ToolGroup[]
}

export async function listToolGroups(platformId: number) {
  const { data } = await http.get<ToolGroupCatalog>(
    `/platforms/${platformId}/tool-groups`
  )
  return data ?? { builtin: [], host: [] }
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
