import { memo, useEffect, useMemo, useRef } from 'react'
import { type Message } from '@/api/chat'
import { ScrollArea } from '@/components/ui/scroll-area'
import { ChatMessage } from './chat-message'

type ChatMessageListProps = {
  conversationId: number | null
  currentUserId?: number
  aiUserId?: number | null
  messages: Message[]
  showSender?: boolean
}

const NEAR_BOTTOM_THRESHOLD = 80

export const ChatMessageList = memo(function ChatMessageList({
  conversationId,
  currentUserId,
  aiUserId,
  messages,
  showSender = false,
}: ChatMessageListProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const isNearBottomRef = useRef(true)
  const lastConversationIdRef = useRef<number | null>(null)
  const lastMessageIdRef = useRef<number | null>(null)

  const scrollToBottom = () => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }

  useEffect(() => {
    const viewport = containerRef.current?.querySelector<HTMLDivElement>(
      '[data-slot="scroll-area-viewport"]'
    )
    if (!viewport) return

    const updateNearBottom = () => {
      const distanceToBottom =
        viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight
      isNearBottomRef.current = distanceToBottom <= NEAR_BOTTOM_THRESHOLD
    }

    updateNearBottom()
    viewport.addEventListener('scroll', updateNearBottom)

    return () => {
      viewport.removeEventListener('scroll', updateNearBottom)
    }
  }, [conversationId])

  useEffect(() => {
    const latestMessage = messages[0]
    const latestMessageId = latestMessage ? Number(latestMessage.id) : null
    const conversationChanged =
      Number(lastConversationIdRef.current) !== Number(conversationId)

    if (!conversationId) {
      lastConversationIdRef.current = null
      lastMessageIdRef.current = latestMessageId
      return
    }

    if (conversationChanged) {
      lastConversationIdRef.current = conversationId
      lastMessageIdRef.current = latestMessageId
      const frameId = requestAnimationFrame(scrollToBottom)
      return () => cancelAnimationFrame(frameId)
    }

    if (latestMessageId === null || latestMessageId === lastMessageIdRef.current) return

    const mine = Number(latestMessage?.sender_id) === Number(currentUserId)
    lastMessageIdRef.current = latestMessageId

    if (!mine && !isNearBottomRef.current) return

    const frameId = requestAnimationFrame(scrollToBottom)
    return () => cancelAnimationFrame(frameId)
  }, [conversationId, currentUserId, messages])

  const orderedMessages = useMemo(() => messages.slice().reverse(), [messages])

  return (
    <div ref={containerRef} className='min-h-0 min-w-0 flex-1'>
      <ScrollArea className='h-full w-full'>
        <div className='grid w-full min-w-0 max-w-full gap-3 pb-4'>
          {orderedMessages.map((m) => (
              <ChatMessage
                key={m.id}
                message={m}
                mine={Number(m.sender_id) === Number(currentUserId)}
                aiUserId={aiUserId}
                showSender={showSender}
              />
            ))}

          {conversationId && messages.length === 0 && (
            <div className='py-8 text-center text-sm text-muted-foreground'>
              No messages
            </div>
          )}

          {!conversationId && (
            <div className='py-8 text-center text-sm text-muted-foreground'>
              Select a conversation
            </div>
          )}
          <div ref={bottomRef} aria-hidden='true' />
        </div>
      </ScrollArea>
    </div>
  )
})
