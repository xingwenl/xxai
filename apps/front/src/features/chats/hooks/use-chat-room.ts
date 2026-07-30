import { useEffect } from 'react'
import { connectChatSocket } from '@/lib/chat-socket'

export function useChatRoom({
  token,
  conversationId,
}: {
  token?: string | null
  conversationId?: number | null
}) {
  useEffect(() => {
    if (!token) return
    if (!conversationId) return
    const s = connectChatSocket(token)
    s.emit('joinConversation', Number(conversationId))
    return () => {
      s.emit('leaveConversation', Number(conversationId))
    }
  }, [conversationId, token])
}
