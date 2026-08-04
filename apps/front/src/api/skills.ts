import { http } from '@/lib/http'

export type Skill = {
  id: number
  platform_id: number
  package_id?: number | null
  name: string
  slug: string
  description?: string | null
  instruction_template: string
  parameter_schema: Record<string, unknown>
  lifecycle_hooks: Record<string, unknown>
  package_skill_path?: string | null
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

export type SkillPackageFile = {
  id: number
  package_id: number
  relative_path: string
  role: string
  size_bytes: number
  media_type?: string | null
  created_at: string
  updated_at: string
}

export type SkillPackage = {
  id: number
  platform_id: number
  name: string
  slug: string
  package_type: string
  source_filename: string
  storage_key: string
  storage_path: string
  manifest: Record<string, unknown>
  warnings: string[]
  allow_script_execution: boolean
  is_active: boolean
  created_at: string
  updated_at: string
  files?: SkillPackageFile[]
  skills?: Skill[]
}

export type SkillPackagePage = {
  items: SkillPackage[]
  total: number
  page: number
  pageSize: number
  totalPage: number
}

export type SkillPackageInput = {
  allow_script_execution?: boolean
  is_active?: boolean
}

export type SkillImportResult = {
  package: SkillPackage
  warnings: string[]
}

export type SkillScriptExecution = {
  id: number
  platform_id: number
  package_id: number
  skill_id: number
  agent_id: number
  user_id?: number | null
  platform_end_user_id?: number | null
  conversation_id?: number | null
  request_id?: string | null
  script_path: string
  arguments: string[]
  status: string
  exit_code?: number | null
  stdout?: string | null
  stderr?: string | null
  error?: string | null
  duration_ms?: number | null
  started_at?: string | null
  completed_at?: string | null
  created_at: string
  updated_at: string
}

export async function listSkillScriptExecutions(platformId: number) {
  const { data } = await http.get<BackendSkillScriptExecutionPage>(
    `/platforms/${platformId}/skill-script-executions`
  )
  return {
    items: data?.items ?? [],
    total: Number(data?.total ?? 0),
  }
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

export async function importSkillPackage(
  platformId: number,
  file: File
): Promise<SkillImportResult> {
  const formData = new FormData()
  formData.append('file', file)
  const { data } = await http.post<SkillImportResult>(
    `/platforms/${platformId}/skills/import`,
    formData
  )
  return data
}

export async function listSkillPackages(
  platformId: number,
  params: { page?: number; pageSize?: number } = {}
): Promise<SkillPackagePage> {
  const { data } = await http.get<BackendSkillPackagePage>(
    `/platforms/${platformId}/skill-packages`,
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

export async function getSkillPackage(
  platformId: number,
  packageId: number
): Promise<SkillPackage> {
  const { data } = await http.get<SkillPackage>(
    `/platforms/${platformId}/skill-packages/${packageId}`
  )
  return data
}

export async function updateSkillPackage(
  platformId: number,
  packageId: number,
  input: SkillPackageInput
) {
  const { data } = await http.patch<SkillPackage>(
    `/platforms/${platformId}/skill-packages/${packageId}`,
    input
  )
  return data
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

type BackendSkillPackagePage = {
  page_no: number
  page_size: number
  items: SkillPackage[]
  total: number
  pages: number
}

type BackendSkillScriptExecutionPage = {
  items: SkillScriptExecution[]
  total: number
  page_no: number
  page_size: number
  pages: number
}
