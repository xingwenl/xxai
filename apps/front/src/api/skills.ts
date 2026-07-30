import { http } from '@/lib/http'

export type Skill = {
  id: number
  platform_id: number
  name: string
  slug: string
  description?: string | null
  instruction_template: string
  parameter_schema: Record<string, unknown>
  lifecycle_hooks: Record<string, unknown>
  is_active: boolean
  created_at: string
  updated_at: string
}

export type SkillPage = {
  items: Skill[]
  total: number
  page: number
  pageSize: number
  totalPage: number
}

export type SkillInput = {
  name: string
  slug: string
  description?: string
  instruction_template: string
  parameter_schema: Record<string, unknown>
  lifecycle_hooks: Record<string, unknown>
}

export type SkillUpdateInput = Omit<SkillInput, 'slug'> & { is_active: boolean }

export type AgentSkillBinding = {
  id: number
  agent_id: number
  skill_id: number
  sort_order: number
  is_enabled: boolean
  created_at: string
  updated_at: string
}

export async function listSkills(
  platformId: number,
  params: { page?: number; pageSize?: number } = {}
): Promise<SkillPage> {
  const { data } = await http.get<BackendSkillPage>(
    `/platforms/${platformId}/skills`,
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

export async function createSkill(platformId: number, input: SkillInput) {
  const { data } = await http.post<Skill>(
    `/platforms/${platformId}/skills`,
    input
  )
  return data
}

export async function updateSkill(
  platformId: number,
  skillId: number,
  input: SkillUpdateInput
) {
  const { data } = await http.patch<Skill>(
    `/platforms/${platformId}/skills/${skillId}`,
    input
  )
  return data
}

export async function deleteSkill(platformId: number, skillId: number) {
  await http.delete(`/platforms/${platformId}/skills/${skillId}`)
}

export async function listAgentSkills(platformId: number, agentId: number) {
  const { data } = await http.get<AgentSkillBinding[]>(
    `/platforms/${platformId}/agents/${agentId}/skills`
  )
  return data ?? []
}

export async function bindSkill(
  platformId: number,
  agentId: number,
  skillId: number,
  sortOrder = 0
) {
  await http.put(`/platforms/${platformId}/agents/${agentId}/skills`, {
    skill_id: skillId,
    sort_order: sortOrder,
  })
}

export async function unbindSkill(
  platformId: number,
  agentId: number,
  skillId: number
) {
  await http.delete(
    `/platforms/${platformId}/agents/${agentId}/skills/${skillId}`
  )
}

type BackendSkillPage = {
  page_no: number
  page_size: number
  items: Skill[]
  total: number
  pages: number
}
