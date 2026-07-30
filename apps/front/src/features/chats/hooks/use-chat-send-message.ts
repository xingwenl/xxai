import { useCallback } from 'react'
import { toast } from 'sonner'
import type { ChatAttachment } from '@/api/chat'
import { connectChatSocket } from '@/lib/chat-socket'

export type SendChatMessageInput =
  | string
  | {
      content: string
      contentType?: 'text' | 'image' | 'file'
      attachments?: ChatAttachment[]
    }

export function useChatSendMessage({
  token,
  conversationId,
}: {
  token?: string | null
  conversationId?: number | null
}) {
  return useCallback(
    (input: SendChatMessageInput) => {
      if (!token) return
      if (!conversationId) return
      const payload =
        typeof input === 'string'
          ? { content: input, contentType: 'text' as const }
          : {
              content: input.content,
              contentType: input.contentType ?? 'text',
              attachments: input.attachments,
            }
      const s = connectChatSocket(token)
      s.emit(
        'sendMessage',
        {
          conversationId: Number(conversationId),
          ...payload,
        },
        (ack: unknown) => {
          if (
            ack &&
            typeof ack === 'object' &&
            'error' in ack &&
            typeof (ack as { error?: unknown }).error !== 'undefined'
          ) {
            toast.error(
              String((ack as { error?: unknown }).error || 'Send failed')
            )
          }
        }
      )
    },
    [conversationId, token]
  )
}
