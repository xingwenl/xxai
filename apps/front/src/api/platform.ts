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

export async function listPlatforms(): Promise<Platform[]> {
  const { data } = await http.get<Platform[]>('/platforms')
  return data ?? []
}
