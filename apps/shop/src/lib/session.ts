/** 店铺系统会话：登录成功后暂存浏览器会话（sessionStorage），不落库。 */

export interface ShopSession {
  shopToken: string
  shopUserId: string
  displayName?: string
  expiresIn?: number
}

const TOKEN_KEY = 'shop_agent_shop_token'
const USER_KEY = 'shop_agent_shop_user'

export function saveSession(session: ShopSession): void {
  sessionStorage.setItem(TOKEN_KEY, session.shopToken)
  sessionStorage.setItem(USER_KEY, JSON.stringify({
    shopUserId: session.shopUserId,
    displayName: session.displayName,
    expiresIn: session.expiresIn,
  }))
}

export function loadSession(): ShopSession | null {
  const token = sessionStorage.getItem(TOKEN_KEY)
  const rawUser = sessionStorage.getItem(USER_KEY)
  if (!token || !rawUser) return null
  try {
    const user = JSON.parse(rawUser) as { shopUserId: string; displayName?: string; expiresIn?: number }
    return { shopToken: token, ...user }
  } catch {
    return null
  }
}

export function clearSession(): void {
  sessionStorage.removeItem(TOKEN_KEY)
  sessionStorage.removeItem(USER_KEY)
}
