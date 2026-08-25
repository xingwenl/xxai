/**
 * 解析聊天窗口头部显示的 agent 名称。
 *
 * 网关在认证成功后下发 embed client 名称，优先展示；旧网关或未配置
 * client 名称时回退到调用方传入的 title。
 */
export function resolveHeaderName(clientName?: string | null, title?: string): string {
  const trimmed = clientName?.trim()
  if (trimmed) return trimmed
  return title?.trim() || 'AI Assistant'
}
