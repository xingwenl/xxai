/**
 * 后端会话 payload → SDK `Message` 的唯一映射点。
 *
 * `AgentClient.fetchHistory()` 与 `ConversationHistory.vue` 共用这里的实现，
 * 保证「后台会话记录里看到的 Loop」与「embed 聊天窗口里看到的 Loop」同源
 * （ADR 0003 的「投影唯一 / SDK 边界」两条约束）。
 */
import type { Message } from '../core'

/**
 * 映射函数的入参形状：字段全部可选，只描述本函数真正读取的键。
 *
 * 之所以放宽到可选：既有 `fetchHistory` 拿到的响应体本就可能是任意 JSON，
 * 而 `ConversationMessagePayload` 是给宿主实现的冻结契约。两者共用同一份
 * 实现时，缺字段走兜底而不是抛错。
 */
export interface HistoryMessageLike {
  id: number | string
  role?: string | null
  content?: string | null
  content_blocks?: Message['contentBlocks'] | null
  created_at?: string | null
  loop?: Message['loop'] | null
  requestId?: string | null
  request_id?: string | null
}

/**
 * 单条后端消息 → SDK `Message`。
 *
 * 行为与 `AgentClient.fetchHistory()` 原有内联实现逐字等价：
 * 无 `content_blocks` 时补一个 markdown 文本块；`requestId` 兼容
 * `requestId` / `request_id` 两种拼写；`created_at` 缺失时用当前时间。
 */
export function mapHistoryMessage(
  item: HistoryMessageLike,
  conversationId: string
): Message {
  return {
    id: String(item.id),
    role: (item.role as Message['role']) || 'assistant',
    type: 'text',
    content: { type: 'text', text: item.content || '' },
    contentBlocks: Array.isArray(item.content_blocks) && item.content_blocks.length
      ? item.content_blocks
      : [{
          id: `${item.id}_text`,
          type: 'markdown' as const,
          text: item.content || '',
          status: 'completed' as const
        }],
    loop: item.loop ?? undefined,
    timestamp: item.created_at ? new Date(item.created_at) : new Date(),
    conversationId,
    requestId: item.requestId || item.request_id || undefined
  }
}

/** 数组版：`mapHistoryMessages(payloads, String(conversationId))`。 */
export function mapHistoryMessages(
  payloads: HistoryMessageLike[],
  conversationId: string
): Message[] {
  return payloads.map((item) => mapHistoryMessage(item, conversationId))
}
