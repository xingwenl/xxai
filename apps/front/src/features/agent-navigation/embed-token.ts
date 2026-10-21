/**
 * 从宿主拿到的 Embed token（JWT）里解析 `client_id`。
 *
 * 悬浮助手的 token 由后端用「服务端配置的 Embed Client」签发，载荷里带 `client_id`
 * （见 apps/backend/app/modules/embed/security.py）。SDK 自己不知道当前连接属于哪个
 * Client，因此宿主在需要「该 Client 可见哪些智能体」时，只能从 token 反查，或者要求
 * 部署方额外配置一份 `VITE_AGENT_CLIENT_ID`——后者容易漏配并静默关闭切换能力。
 *
 * 这里只读取 payload，不校验签名：token 的合法性由后端在换签/建连时校验，
 * 本函数的结果仅用于查询「该 Client 的智能体绑定」，调用方还会经过后台鉴权接口。
 */
export function readEmbedTokenClientId(
  accessToken: string | null | undefined
): string | undefined {
  if (!accessToken) return undefined
  const payload = accessToken.split('.')[1]
  if (!payload) return undefined

  try {
    // JWT 的 payload 是 base64url（`-`/`_` 替换 `+`/`/`，且省略尾部 `=`）。
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=')
    const claims: unknown = JSON.parse(atob(padded))
    if (!claims || typeof claims !== 'object') return undefined
    const clientId = (claims as { client_id?: unknown }).client_id
    return typeof clientId === 'string' && clientId.trim()
      ? clientId
      : undefined
  } catch {
    // payload 不是合法 JSON/base64 时按「解析不到」处理，调用方会退化为不展示切换入口。
    return undefined
  }
}
