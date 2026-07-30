import { useEffect, useRef } from 'react'
import type { QueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { connectChatSocket } from '@/lib/chat-socket'
import type { Conversation, Message, Paginated } from '@/api/chat'

type StreamState = {
  conversationId: number
  tempId: number
  senderId: number
  buffer: string
  timer: number | null
}

type MessageStreamStart = {
  streamId: string
  conversation_id: number
  sender_id: number
  content_type: 'text'
  create_time: string
}

type MessageStreamDelta = {
  streamId: string
  conversation_id: number
  delta: string
}

type MessageStreamDone = {
  streamId: string
  conversation_id: number
  finalMessage: Message
}

type MessageStreamError = {
  streamId: string
  conversation_id: number
  error: { message: string }
}

function formatIncomingMessagePreview(message: Message) {
  if (message.content_type === 'image') return '[图片]'
  if (message.content_type === 'file') {
    const first = message.attachments?.[0]
    return `[文件] ${first?.originalName || '附件'}`
  }
  const content = String(message.content || '').trim()
  return content.length > 60 ? `${content.slice(0, 60)}...` : content || '新消息'
}

function findConversationName(
  conversations: Conversation[],
  conversationId: number,
  currentUserId?: number | null
) {
  const current = conversations.find(
    (item) => Number(item.id) === Number(conversationId)
  )
  if (!current) return '聊天'
  if (current.type === 'group') return current.name || '群聊'
  const other =
    current.participants_users?.find(
      (item) => Number(item.id) !== Number(currentUserId)
    ) ?? current.participants_users?.[0]
  return (
    other?.nickname ||
    other?.username ||
    other?.id?.toString() ||
    '聊天'
  )
}

export function shouldNotifyIncomingMessage({
  message,
  currentUserId,
  selectedConversationId,
}: {
  message: Message
  currentUserId?: number | null
  selectedConversationId?: number | null
}) {
  if (!currentUserId) return false
  if (Number(message.sender_id) === Number(currentUserId)) return false
  if (Number(selectedConversationId) === Number(message.conversation_id)) {
    return false
  }
  return true
}

export function useChatSocketEvents({
  token,
  qc,
  currentUserId,
  selectedConversationId,
}: {
  token?: string | null
  qc: QueryClient
  currentUserId?: number | null
  selectedConversationId?: number | null
}) {
  const streamStateRef = useRef(new Map<string, StreamState>())

  useEffect(() => {
    if (!token) return
    const s = connectChatSocket(token)
    const streamStates = streamStateRef.current

    const onMessage = (msg: Message) => {
      qc.invalidateQueries({ queryKey: ['chat', 'conversations'] })
      const key = [
        'chat',
        'messages',
        { id: msg.conversation_id, page: 1, pageSize: 50 },
      ] as const
      qc.setQueryData<Paginated<Message>>(key, (old) => {
        if (!old) return old
        const exists = old.items.some((m) => Number(m.id) === Number(msg.id))
        if (exists) return old
        return { ...old, items: [msg, ...old.items] }
      })

      if (
        shouldNotifyIncomingMessage({
          message: msg,
          currentUserId,
          selectedConversationId,
        })
      ) {
        const conversations =
          qc.getQueryData<Paginated<Conversation>>([
            'chat',
            'conversations',
            { page: 1, pageSize: 50 },
          ])?.items ?? []
        toast.message(`新消息 · ${findConversationName(conversations, msg.conversation_id, currentUserId)}`, {
          description: formatIncomingMessagePreview(msg),
        })
      }
    }

    const flushStream = (streamId: string) => {
      const state = streamStates.get(streamId)
      if (!state) return
      const buf = state.buffer
      if (!buf) return
      state.buffer = ''

      const key = [
        'chat',
        'messages',
        { id: state.conversationId, page: 1, pageSize: 50 },
      ] as const
      qc.setQueryData<Paginated<Message>>(key, (old) => {
        if (!old) return old
        return {
          ...old,
          items: old.items.map((m) =>
            Number(m.id) === Number(state.tempId)
              ? { ...m, content: String(m.content || '') + buf }
              : m,
          ),
        }
      })
    }

    const onStreamStart = (p: MessageStreamStart) => {
      qc.invalidateQueries({ queryKey: ['chat', 'conversations'] })
      const streamId = String(p.streamId || '').trim()
      const conversationId = Number(p.conversation_id)
      if (!streamId || !Number.isFinite(conversationId)) return
      if (streamStates.has(streamId)) return

      const tempId = -Date.now()
      streamStates.set(streamId, {
        conversationId,
        tempId,
        senderId: Number(p.sender_id),
        buffer: '',
        timer: null,
      })

      const key = [
        'chat',
        'messages',
        { id: conversationId, page: 1, pageSize: 50 },
      ] as const
      qc.setQueryData<Paginated<Message>>(key, (old) => {
        if (!old) return old
        const exists = old.items.some((m) => Number(m.id) === Number(tempId))
        if (exists) return old
        const temp: Message = {
          id: tempId,
          conversation_id: conversationId,
          sender_id: Number(p.sender_id),
          content: '',
          content_type: 'text',
          create_time: p.create_time || new Date().toISOString(),
        }
        return { ...old, items: [temp, ...old.items] }
      })
    }

    const onStreamDelta = (p: MessageStreamDelta) => {
      const streamId = String(p.streamId || '').trim()
      const state = streamStates.get(streamId)
      if (!state) return
      state.buffer += String(p.delta || '')
      if (state.timer) return
      state.timer = window.setTimeout(() => {
        const s0 = streamStates.get(streamId)
        if (s0) s0.timer = null
        flushStream(streamId)
      }, 50)
    }

    const onStreamDone = (p: MessageStreamDone) => {
      const streamId = String(p.streamId || '').trim()
      const state = streamStates.get(streamId)
      if (!state) return

      if (state.timer) {
        window.clearTimeout(state.timer)
        state.timer = null
      }
      flushStream(streamId)
      streamStates.delete(streamId)

      const key = [
        'chat',
        'messages',
        { id: state.conversationId, page: 1, pageSize: 50 },
      ] as const
      qc.setQueryData<Paginated<Message>>(key, (old) => {
        if (!old) return old
        const filtered = old.items.filter(
          (m) => Number(m.id) !== Number(state.tempId),
        )
        const exists = filtered.some(
          (m) => Number(m.id) === Number(p.finalMessage.id),
        )
        return exists
          ? { ...old, items: filtered }
          : { ...old, items: [p.finalMessage, ...filtered] }
      })
    }

    const onStreamError = (p: MessageStreamError) => {
      const streamId = String(p.streamId || '').trim()
      const state = streamStates.get(streamId)
      if (!state) return

      if (state.timer) {
        window.clearTimeout(state.timer)
        state.timer = null
      }
      streamStates.delete(streamId)

      const key = [
        'chat',
        'messages',
        { id: state.conversationId, page: 1, pageSize: 50 },
      ] as const
      qc.setQueryData<Paginated<Message>>(key, (old) => {
        if (!old) return old
        return {
          ...old,
          items: old.items.filter((m) => Number(m.id) !== Number(state.tempId)),
        }
      })

      toast.error(String(p.error?.message || 'AI stream error'))
    }

    s.on('message', onMessage)
    s.on('message_stream_start', onStreamStart)
    s.on('message_stream_delta', onStreamDelta)
    s.on('message_stream_done', onStreamDone)
    s.on('message_stream_error', onStreamError)

    return () => {
      s.off('message', onMessage)
      s.off('message_stream_start', onStreamStart)
      s.off('message_stream_delta', onStreamDelta)
      s.off('message_stream_done', onStreamDone)
      s.off('message_stream_error', onStreamError)

      for (const [, st] of streamStates) {
        if (st.timer) window.clearTimeout(st.timer)
      }
      streamStates.clear()
    }
  }, [currentUserId, qc, selectedConversationId, token])
}
