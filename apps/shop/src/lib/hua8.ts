/** 店铺运营平台（hua8）登录接口封装与 JWT 解析。 */

const HUA8_BASE = import.meta.env.VITE_HUA8_BASE ?? ''

export interface CaptchaInfo {
  uuid: string
  img: string
  captchaEnabled: boolean
}

export async function fetchCaptcha(): Promise<CaptchaInfo> {
  const response = await fetch(`${HUA8_BASE}/hua8-api/code`, {
    headers: { Accept: 'text/plain' },
  })
  const body = await response.json()
  return {
    uuid: body.uuid ?? '',
    img: body.img ?? '',
    captchaEnabled: body.captchaEnabled !== false,
  }
}

export interface LoginResult {
  accessToken: string
  expiresIn: number
}

export async function login(
  username: string,
  password: string,
  code: string,
  uuid: string,
): Promise<LoginResult> {
  const response = await fetch(`${HUA8_BASE}/hua8-api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json;charset=UTF-8' },
    body: JSON.stringify({ username, password, code, uuid }),
  })
  const body = await response.json()
  if (body.code !== 200 || !body.data?.access_token) {
    throw new Error(body.msg || `登录失败（HTTP ${response.status}）`)
  }
  return { accessToken: body.data.access_token, expiresIn: body.data.expires_in }
}

function base64UrlDecode(input: string): string {
  const b64 = input.replace(/-/g, '+').replace(/_/g, '/')
  const padded = b64.padEnd(Math.ceil(b64.length / 4) * 4, '=')
  const bytes = Uint8Array.from(atob(padded), (char) => char.charCodeAt(0))
  return new TextDecoder().decode(bytes)
}

export interface ShopJwtPayload {
  user_id?: number | string
  username?: string
  tenant_id?: number | string
}

export function decodeShopJwt(token: string): ShopJwtPayload {
  const parts = token.split('.')
  if (parts.length < 2) return {}
  try {
    return JSON.parse(base64UrlDecode(parts[1])) as ShopJwtPayload
  } catch {
    return {}
  }
}
