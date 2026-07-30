import { http } from '@/lib/http'

export type Friend = {
  id: number
  username: string
  avatar?: string | null
  nickname?: string | null
  alias?: string | null
  is_bot?: number
}

export type FriendRequest = {
  requestId: number
  userId: number
  username: string
  avatar?: string | null
  nickname?: string | null
  alias?: string | null
  is_bot?: number
}

export async function getFriendList(): Promise<Friend[]> {
  const { data } = await http.get<Friend[]>('/api/friend/list')
  return data
}

export async function getFriendRequests(): Promise<FriendRequest[]> {
  const { data } = await http.get<FriendRequest[]>('/api/friend/requests')
  return data
}

export async function applyFriend(req: { friendId: number; alias?: string }) {
  const { data } = await http.post('/api/friend/apply', req)
  return data
}

export async function handleFriend(req: { friendId: number; status: 1 | 2 }) {
  const { data } = await http.post('/api/friend/handle', req)
  return data
}

export async function removeFriend(friendId: number) {
  const { data } = await http.delete(`/api/friend/${friendId}`)
  return data
}
