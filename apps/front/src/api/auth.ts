import { http } from '@/lib/http'

export type LoginReq = {
  account: string
  password: string
}

export type LoginRes = {
  access_token: string
  token_type: string
  expires_in: number
}

export type RegisterReq = {
  name: string
  email: string
  account: string
  password: string
}

export type RegisterRes = {
  id: number
  name: string
  email: string
  account: string
  is_active: boolean
}

export async function login(req: LoginReq): Promise<LoginRes> {
  const { data } = await http.post<LoginRes>('/auth/login', req)
  return data
}

export async function register(req: RegisterReq): Promise<RegisterRes> {
  const { data } = await http.post<RegisterRes>('/auth/register', req)
  return data
}
