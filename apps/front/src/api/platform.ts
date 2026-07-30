import { http } from '@/lib/http'

export type Platform = {
  id: number
  name: string
  code: string
  is_active: boolean
  owner_id?: number | null
  created_at: string
  updated_at: string
}

export type PlatformInput = {
  name: string
  code: string
}

export type PlatformUpdateInput = Partial<PlatformInput> & {
  is_active?: boolean
}

export async function listPlatforms(): Promise<Platform[]> {
  const { data } = await http.get<Platform[]>('/platforms')
  return data ?? []
}

export async function createPlatform(input: PlatformInput): Promise<Platform> {
  const { data } = await http.post<Platform>('/platforms', input)
  return data
}

export async function updatePlatform(
  platformId: number,
  input: PlatformUpdateInput
): Promise<Platform> {
  const { data } = await http.patch<Platform>(`/platforms/${platformId}`, input)
  return data
}

export async function deletePlatform(platformId: number) {
  await http.delete(`/platforms/${platformId}`)
}
