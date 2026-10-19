import { http } from '@/lib/http'

export const MODEL_TYPES = [
  'chat',
  'image_generate',
  'image_read',
  'embedding',
] as const

export const BINDING_ROLES = [
  'chat',
  'image_generate',
  'image_read',
  'embedding',
] as const

export type ModelType = (typeof MODEL_TYPES)[number]
export type BindingRole = (typeof BINDING_ROLES)[number]

export type PlatformModel = {
  id: number
  platform_id: number
  name: string
  model_type: ModelType
  model_name: string
  base_url?: string | null
  capabilities?: Record<string, unknown> | null
  options: Record<string, unknown>
  is_active: boolean
  has_api_key: boolean
  created_at: string
  updated_at: string
}

export type PlatformModelInput = {
  name: string
  model_type: ModelType
  model_name: string
  base_url?: string | null
  api_key?: string
  capabilities?: Record<string, unknown> | null
  options?: Record<string, unknown>
  is_active?: boolean
}

export type PlatformModelUpdateInput = Omit<
  Partial<PlatformModelInput>,
  'api_key'
> & {
  api_key?: string
}

export type PlatformModelPage = {
  page_no: number
  page_size: number
  items: PlatformModel[]
  total: number
  pages: number
}

export type AgentModelBindingItem = {
  role: BindingRole
  model_id: number
  model_name: string
  model_type: ModelType
  is_active: boolean
}

export type AgentModelBindings = {
  items: AgentModelBindingItem[]
}

export type AgentModelBindingUpdateItem = {
  role: BindingRole
  model_id: number
}

export async function listPlatformModels(
  platformId: number,
  params: {
    page_no?: number
    page_size?: number
    model_type?: ModelType | ''
  } = {}
): Promise<PlatformModelPage> {
  const { data } = await http.get<PlatformModelPage>(
    `/platforms/${platformId}/models`,
    { params }
  )
  return (
    data ?? {
      page_no: 1,
      page_size: params.page_size ?? 20,
      items: [],
      total: 0,
      pages: 1,
    }
  )
}

export async function createPlatformModel(
  platformId: number,
  input: PlatformModelInput
): Promise<PlatformModel> {
  const { data } = await http.post<PlatformModel>(
    `/platforms/${platformId}/models`,
    input
  )
  return data
}

export async function updatePlatformModel(
  platformId: number,
  modelId: number,
  input: PlatformModelUpdateInput
): Promise<PlatformModel> {
  const { data } = await http.patch<PlatformModel>(
    `/platforms/${platformId}/models/${modelId}`,
    input
  )
  return data
}

export async function deletePlatformModel(platformId: number, modelId: number) {
  await http.delete(`/platforms/${platformId}/models/${modelId}`)
}

export async function listAgentModelBindings(
  platformId: number,
  agentId: number
): Promise<AgentModelBindings> {
  const { data } = await http.get<AgentModelBindings>(
    `/platforms/${platformId}/agents/${agentId}/models`
  )
  return data ?? { items: [] }
}

export async function replaceAgentModelBindings(
  platformId: number,
  agentId: number,
  bindings: AgentModelBindingUpdateItem[]
): Promise<AgentModelBindings> {
  const { data } = await http.put<AgentModelBindings>(
    `/platforms/${platformId}/agents/${agentId}/models`,
    { bindings }
  )
  return data ?? { items: [] }
}
