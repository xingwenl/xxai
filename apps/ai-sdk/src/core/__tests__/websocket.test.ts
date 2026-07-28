import { describe, expect, it, vi } from 'vitest'
import { FakeWebSocket } from '../../test/fake-websocket'
import { WebSocketTransport } from '../websocket'

function event(sequence: number, type: string, payload: Record<string, unknown> = {}) {
  return {
    id: `evt-${sequence}`,
    type,
    protocolVersion: 1,
    sequence,
    timestamp: new Date().toISOString(),
    payload
  }
}

describe('WebSocketTransport', () => {
  it('connects using the endpoint and authenticates after the socket opens', async () => {
    const sockets: FakeWebSocket[] = []
    const factory = (url: string, protocols?: string | string[]) => {
      const socket = new FakeWebSocket(url, protocols)
      sockets.push(socket)
      return socket
    }
    const transport = new WebSocketTransport({
      endpoint: 'wss://agent.test/api/v1/ws/agents/7',
      getToken: vi.fn().mockResolvedValue('secret-token'),
      platformId: 'platform-1',
      agentId: '7',
      websocketFactory: factory
    })

    const connecting = transport.connect()
    expect(sockets[0].url).toBe('wss://agent.test/api/v1/ws/agents/7')
    expect(sockets[0].protocol).toBe('ai-agent.v1')
    expect(sockets[0].sent).toEqual([])
    sockets[0].open()
    await Promise.resolve()
    expect(JSON.parse(sockets[0].sent[0])).toMatchObject({
      type: 'auth',
      payload: { token: 'secret-token', platformId: 'platform-1', agentId: '7' }
    })
    sockets[0].receive(event(1, 'session_ready', { sessionId: 'session-1', recovered: true }))
    await connecting
    expect(transport.state).toBe('connected')
  })

  it('queues messages until session_ready and does not reconnect after explicit disconnect', async () => {
    const socket = new FakeWebSocket('wss://agent.test/ws')
    const transport = new WebSocketTransport({
      endpoint: socket.url,
      getToken: vi.fn().mockResolvedValue('token'),
      platformId: 'p',
      agentId: 'a',
      websocketFactory: () => socket,
      reconnect: { maxRetries: 2, delayMs: 10 }
    })
    const connected = transport.connect()
    transport.send({ type: 'message_send', requestId: 'req-1', payload: { text: 'hi' } })
    socket.open()
    await Promise.resolve()
    expect(socket.sent).toHaveLength(1)
    socket.receive(event(1, 'session_ready', { recovered: false }))
    await connected
    expect(socket.sent).toHaveLength(2)
    expect(JSON.parse(socket.sent[1])).toMatchObject({ type: 'message_send', requestId: 'req-1' })
    transport.disconnect()
    expect(transport.state).toBe('disconnected')
  })

  it('reconnects with exponential backoff after an unexpected close', async () => {
    vi.useFakeTimers()
    const sockets: FakeWebSocket[] = []
    const transport = new WebSocketTransport({
      endpoint: 'wss://agent.test/ws',
      getToken: vi.fn().mockResolvedValue('token'),
      platformId: 'p',
      agentId: 'a',
      websocketFactory: (url, protocols) => {
        const socket = new FakeWebSocket(url, protocols)
        sockets.push(socket)
        return socket
      },
      reconnect: { maxRetries: 2, delayMs: 100 }
    })
    const connected = transport.connect()
    sockets[0].open()
    await Promise.resolve()
    sockets[0].receive(event(1, 'session_ready'))
    await connected
    sockets[0].close(1006)
    expect(transport.state).toBe('reconnecting')
    await vi.advanceTimersByTimeAsync(100)
    expect(sockets).toHaveLength(2)
    vi.useRealTimers()
  })

  it('deduplicates events by sequence and remembers the last cursor', async () => {
    const socket = new FakeWebSocket('wss://agent.test/ws')
    const received: unknown[] = []
    const transport = new WebSocketTransport({
      endpoint: socket.url,
      getToken: vi.fn().mockResolvedValue('token'),
      platformId: 'p',
      agentId: 'a',
      websocketFactory: () => socket
    })
    transport.on('message', (message) => received.push(message))
    const connected = transport.connect()
    socket.open()
    await Promise.resolve()
    socket.receive(event(4, 'session_ready'))
    await connected
    socket.receive(event(5, 'pong'))
    socket.receive(event(5, 'pong'))
    expect(received).toHaveLength(2)
    expect(transport.lastSequence).toBe(5)
  })
})
