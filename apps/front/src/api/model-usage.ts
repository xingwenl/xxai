import { http } from '@/lib/http'

export type ModelUsageQuery = {
  start_date: string
  end_date: string
  agent_id?: number
  client_id?: string
  page?: number
  page_size?: number
}

export type ModelUsageRecord = {
  id: number
  created_at: string
  agent_id: number
  agent_name: string
  client_id?: string | null
  client_name?: string | null
  platform_end_user_id?: number | null
  conversation_id: number
  request_id?: string | null
  model_name?: string | null
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export type ModelUsagePage = {
  page_no: number
  page_size: number
  items: ModelUsageRecord[]
  total: number
  pages: number
}

export type TokenUsageSummary = {
  record_count: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export type AgentUsageSummary = TokenUsageSummary & {
  agent_id: number
  agent_name: string
}

export type ClientUsageSummary = TokenUsageSummary & {
  client_id?: string | null
  client_name?: string | null
}

export type DayUsageSummary = TokenUsageSummary & {
  day: string
}

export type ModelUsageSummary = {
  totals: TokenUsageSummary
  by_agent: AgentUsageSummary[]
  by_client: ClientUsageSummary[]
  by_day: DayUsageSummary[]
}

function toSearchParams(query: ModelUsageQuery) {
  const params = new URLSearchParams({
    start_date: query.start_date,
    end_date: query.end_date,
  })
  if (query.agent_id != null) params.set('agent_id', String(query.agent_id))
  if (query.client_id) params.set('client_id', query.client_id)
  if (query.page != null) params.set('page', String(query.page))
  if (query.page_size != null) params.set('page_size', String(query.page_size))
  return params
}

export async function listModelUsage(
  platformId: number,
  query: ModelUsageQuery
) {
  const { data } = await http.get<ModelUsagePage>(
    `/platforms/${platformId}/model-usage-records?${toSearchParams(query)}`
  )
  return data
}

export async function getModelUsageSummary(
  platformId: number,
  query: ModelUsageQuery
) {
  const { data } = await http.get<ModelUsageSummary>(
    `/platforms/${platformId}/model-usage-records/summary?${toSearchParams(query)}`
  )
  return data
}
