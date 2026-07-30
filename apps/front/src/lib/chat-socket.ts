import { io, type Socket } from 'socket.io-client'

export type ChatSocket = Socket

let socket: ChatSocket | null = null
let lastToken: string | null = null

export function getChatSocket() {
  return socket
}

export function connectChatSocket(token: string) {
  const baseUrl = import.meta.env.VITE_WS_URL ?? ''

  if (!socket) {
    socket = io(`${baseUrl}/chat`, {
      transports: ['websocket'],
      autoConnect: false,
    })
  }

  if (lastToken !== token) {
    ;(socket as unknown as { auth?: unknown }).auth = { token }
    lastToken = token
  }

  if (!socket.connected) socket.connect()
  return socket
}

export function disconnectChatSocket() {
  if (!socket) return
  try {
    socket.disconnect()
  } finally {
    socket = null
    lastToken = null
  }
}
