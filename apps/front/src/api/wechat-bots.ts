import { http } from '@/lib/http'

export type WeChatBotBinding = {
  id: number
  platform_id: number
  user_id: number
  agent_id: number | null
  status: string
  ilink_bot_id: string | null
  ilink_user_id: string | null
  last_error: string | null
  last_login_at: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export type WeChatBotBindingCreated = {
  binding: WeChatBotBinding
  qrcode: string
  api_token: string
}

export type WeChatBotBindingStatus = {
  status: string
  message: string
  last_login_at: string | null
}

export type WeChatBotBindingInput = {
  agent_id?: number | null
  is_active?: boolean
}

export async function listWeChatBots(
  platformId: number
): Promise<WeChatBotBinding[]> {
  const { data } = await http.get<WeChatBotBinding[]>(
    `/platforms/${platformId}/wechat-bots`
  )
  return data ?? []
}

export async function createWeChatBot(
  platformId: number,
  input: WeChatBotBindingInput
): Promise<WeChatBotBindingCreated> {
  const { data } = await http.post<WeChatBotBindingCreated>(
    `/platforms/${platformId}/wechat-bots`,
    input
  )
  return data
}

export async function getWeChatBotStatus(
  platformId: number,
  bindingId: number
): Promise<WeChatBotBindingStatus> {
  const { data } = await http.get<WeChatBotBindingStatus>(
    `/platforms/${platformId}/wechat-bots/${bindingId}/status`
  )
  return data
}

export async function submitWeChatBotVerifyCode(
  platformId: number,
  bindingId: number,
  verifyCode: string
): Promise<WeChatBotBindingStatus> {
  const { data } = await http.post<WeChatBotBindingStatus>(
    `/platforms/${platformId}/wechat-bots/${bindingId}/verify-code`,
    { verify_code: verifyCode }
  )
  return data
}

export async function updateWeChatBot(
  platformId: number,
  bindingId: number,
  input: WeChatBotBindingInput
): Promise<WeChatBotBinding> {
  const { data } = await http.patch<WeChatBotBinding>(
    `/platforms/${platformId}/wechat-bots/${bindingId}`,
    input
  )
  return data
}

export async function deleteWeChatBot(
  platformId: number,
  bindingId: number
): Promise<void> {
  await http.delete(`/platforms/${platformId}/wechat-bots/${bindingId}`)
}
