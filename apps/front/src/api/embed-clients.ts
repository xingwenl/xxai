import { http } from '@/lib/http'

export type EmbedClient = {
  id: number
  platform_id: number
  client_id: string
  name: string
  allowed_origins: string[]
  token_ttl_seconds: number
  is_active: boolean
  max_tokens_per_minute?: number | null
  max_connections?: number | null
}

export type EmbedClientInput = {
  name: string
  allowed_origins: string[]
  token_ttl_seconds: number
  max_tokens_per_minute?: number | null
  max_connections?: number | null
}

export type EmbedClientUpdateInput = Partial<EmbedClientInput> & {
  is_active?: boolean
}

export type EmbedClientCreated = {
  client: EmbedClient
  client_secret: string
}

export type EmbedClientAgentBinding = {
  id: number
  client_id: number
  agent_id: number
}

export async function listEmbedClients(platformId: number) {
  const { data } = await http.get<EmbedClient[]>(
    `/platforms/${platformId}/embed-clients`
  )
  return data ?? []
}

export async function createEmbedClient(
  platformId: number,
  input: EmbedClientInput
) {
  const { data } = await http.post<EmbedClientCreated>(
    `/platforms/${platformId}/embed-clients`,
    input
  )
  return data
}

export async function updateEmbedClient(
  platformId: number,
  clientId: string,
  input: EmbedClientUpdateInput
) {
  const { data } = await http.patch<EmbedClient>(
    `/platforms/${platformId}/embed-clients/${clientId}`,
    input
  )
  return data
}

export async function rotateEmbedClientSecret(
  platformId: number,
  clientId: string
) {
  const { data } = await http.post<{ client_secret: string }>(
    `/platforms/${platformId}/embed-clients/${clientId}/rotate-secret`
  )
  return data
}

export async function listEmbedClientAgents(
  platformId: number,
  clientId: string
) {
  const { data } = await http.get<EmbedClientAgentBinding[]>(
    `/platforms/${platformId}/embed-clients/${clientId}/agents`
  )
  return data ?? []
}

export async function bindEmbedClientAgent(
  platformId: number,
  clientId: string,
  agentId: number
) {
  await http.put(
    `/platforms/${platformId}/embed-clients/${clientId}/agents/${agentId}`
  )
}

export async function unbindEmbedClientAgent(
  platformId: number,
  clientId: string,
  agentId: number
) {
  await http.delete(
    `/platforms/${platformId}/embed-clients/${clientId}/agents/${agentId}`
  )
}
