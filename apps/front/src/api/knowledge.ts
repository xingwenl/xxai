import { http } from '@/lib/http'

export type KnowledgeBase = {
  id: number
  platform_id: number
  name: string
  slug: string
  embedding_model: string
  embedding_base_url?: string | null
  embedding_dimension: number
  active_index_version: number
  chunk_size: number
  chunk_overlap: number
  retrieval_threshold: number
  retrieval_top_k: number
  has_embedding_api_key: boolean
  created_at: string
  updated_at: string
}

export type KnowledgeBasePage = {
  items: KnowledgeBase[]
  total: number
  page: number
  pageSize: number
  totalPage: number
}

export type KnowledgeBaseInput = {
  name: string
  slug: string
  embedding_model: string
  embedding_base_url?: string | null
  embedding_api_key?: string | null
  embedding_dimension: number
  chunk_size: number
  chunk_overlap: number
  retrieval_threshold: number
  retrieval_top_k: number
}

export type KnowledgeDocument = {
  id: number
  knowledge_base_id: number
  source_type: 'file' | 'url' | string
  title: string
  source_url?: string | null
  media_type?: string | null
  status: 'pending' | 'processing' | 'ready' | 'failed' | string
  error_message?: string | null
  created_at: string
  updated_at: string
}

export type AgentKnowledgeBaseBinding = {
  agent_id: number
  knowledge_base_id: number
}

export async function listKnowledgeBases(
  platformId: number,
  params: { page?: number; pageSize?: number } = {}
): Promise<KnowledgeBasePage> {
  const { data } = await http.get<BackendKnowledgeBasePage>(
    `/platforms/${platformId}/knowledge-bases`,
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

export async function createKnowledgeBase(
  platformId: number,
  input: KnowledgeBaseInput
): Promise<KnowledgeBase> {
  const { data } = await http.post<KnowledgeBase>(
    `/platforms/${platformId}/knowledge-bases`,
    normalizeKnowledgeBaseInput(input)
  )
  return data
}

export async function updateKnowledgeBase(
  platformId: number,
  baseId: number,
  input: Partial<KnowledgeBaseInput>
): Promise<KnowledgeBase> {
  const { data } = await http.patch<KnowledgeBase>(
    `/platforms/${platformId}/knowledge-bases/${baseId}`,
    normalizeKnowledgeBaseInput(input)
  )
  return data
}

export function normalizeKnowledgeBaseInput<
  T extends Partial<KnowledgeBaseInput>,
>(input: T): T {
  return {
    ...input,
    embedding_base_url: normalizeOptionalString(input.embedding_base_url),
    embedding_api_key: normalizeOptionalString(input.embedding_api_key),
  }
}

function normalizeOptionalString(value: string | null | undefined) {
  const trimmed = value?.trim()
  return trimmed ? trimmed : undefined
}

export async function deleteKnowledgeBase(platformId: number, baseId: number) {
  await http.delete(`/platforms/${platformId}/knowledge-bases/${baseId}`)
}

export async function listKnowledgeDocuments(
  platformId: number,
  baseId: number
): Promise<KnowledgeDocument[]> {
  const { data } = await http.get<KnowledgeDocument[]>(
    `/platforms/${platformId}/knowledge-bases/${baseId}/documents`
  )
  return data ?? []
}

export async function uploadKnowledgeDocument(
  platformId: number,
  baseId: number,
  file: File
) {
  const form = new FormData()
  form.append('upload', file)
  const { data } = await http.post<KnowledgeDocument>(
    `/platforms/${platformId}/knowledge-bases/${baseId}/documents/file`,
    form,
    { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 60_000 }
  )
  return data
}

export async function createUrlDocument(
  platformId: number,
  baseId: number,
  input: { url: string; title?: string }
) {
  const { data } = await http.post<KnowledgeDocument>(
    `/platforms/${platformId}/knowledge-bases/${baseId}/documents/url`,
    input
  )
  return data
}

export async function deleteKnowledgeDocument(
  platformId: number,
  baseId: number,
  documentId: number
) {
  await http.delete(
    `/platforms/${platformId}/knowledge-bases/${baseId}/documents/${documentId}`
  )
}

export async function retryKnowledgeDocument(
  platformId: number,
  baseId: number,
  documentId: number
) {
  const { data } = await http.post<KnowledgeDocument>(
    `/platforms/${platformId}/knowledge-bases/${baseId}/documents/${documentId}/retry`
  )
  return data
}

export async function bindKnowledgeBaseAgent(
  platformId: number,
  baseId: number,
  agentId: number,
  sortOrder = 0
): Promise<AgentKnowledgeBaseBinding> {
  const { data } = await http.put<AgentKnowledgeBaseBinding>(
    `/platforms/${platformId}/knowledge-bases/${baseId}/agents/${agentId}`,
    {
      knowledge_base_id: baseId,
      sort_order: sortOrder,
    }
  )
  return data
}

type BackendKnowledgeBasePage = {
  page_no: number
  page_size: number
  items: KnowledgeBase[]
  total: number
  pages: number
}
