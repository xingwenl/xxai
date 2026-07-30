import { useEffect, useState } from 'react'
import {
  connectChatSocket,
  disconnectChatSocket,
  getChatSocket,
} from '@/lib/chat-socket'

export function useChatSocketConnection(token?: string | null) {
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    if (!token) {
      disconnectChatSocket()
      return
    }

    const s = connectChatSocket(token)

    const onConnect = () => setConnected(true)
    const onDisconnect = () => setConnected(false)

    s.on('connect', onConnect)
    s.on('disconnect', onDisconnect)

    return () => {
      s.off('connect', onConnect)
      s.off('disconnect', onDisconnect)
    }
  }, [token])

  return {
    connected: token ? connected || Boolean(getChatSocket()?.connected) : false,
  }
}
