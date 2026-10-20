import { http } from '@/lib/http'

export type MemoryKind = 'fact' | 'event'
export type MemorySource = 'explicit' | 'inferred'

export type MemoryItem = {
  id: number
  platform_id: number
  kind: MemoryKind
  key: string | null
  content: string
  occurred_at: string | null
  valid_until: string | null
  source: MemorySource
  source_conversation_id: number | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export type MemoryListData = {
  items: MemoryItem[]
  total: number
  fact_count: number
  event_count: number
}

export type MemoryStats = {
  fact_count: number
  event_count: number
  total: number
}

export type MemoryCreateInput = {
  kind: MemoryKind
  key?: string | null
  content: string
  occurred_at?: string | null
}

export type MemoryUpdateInput = {
  content?: string
  occurred_at?: string | null
}

export type MemoryQuery = {
  kind?: MemoryKind
  includeHistory?: boolean
  query?: string
}

export async function listMemories(
  platformId: number,
  params: MemoryQuery = {}
): Promise<MemoryListData> {
  const { data } = await http.get<MemoryListData>(
    `/platforms/${platformId}/me/memories`,
    {
      params: {
        kind: params.kind,
        include_history: params.includeHistory || undefined,
        query: params.query || undefined,
      },
    }
  )
  return {
    items: data?.items ?? [],
    total: data?.total ?? 0,
    fact_count: data?.fact_count ?? 0,
    event_count: data?.event_count ?? 0,
  }
}

export async function createMemory(
  platformId: number,
  input: MemoryCreateInput
): Promise<MemoryItem> {
  const { data } = await http.post<MemoryItem>(
    `/platforms/${platformId}/me/memories`,
    input
  )
  return data
}

export async function updateMemory(
  platformId: number,
  memoryId: number,
  input: MemoryUpdateInput
): Promise<MemoryItem> {
  const { data } = await http.patch<MemoryItem>(
    `/platforms/${platformId}/me/memories/${memoryId}`,
    input
  )
  return data
}

export async function deleteMemory(
  platformId: number,
  memoryId: number
): Promise<void> {
  await http.delete(`/platforms/${platformId}/me/memories/${memoryId}`)
}

export async function clearMemories(platformId: number): Promise<number> {
  const { data } = await http.delete<{ deleted: number }>(
    `/platforms/${platformId}/me/memories`
  )
  return data?.deleted ?? 0
}

export async function getMemoryStats(platformId: number): Promise<MemoryStats> {
  const { data } = await http.get<MemoryStats>(
    `/platforms/${platformId}/me/memories/stats`
  )
  return {
    fact_count: data?.fact_count ?? 0,
    event_count: data?.event_count ?? 0,
    total: data?.total ?? 0,
  }
}
