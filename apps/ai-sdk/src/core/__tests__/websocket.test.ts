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

  it('passes the token provider connection context', async () => {
    const socket = new FakeWebSocket('wss://agent.test/ws')
    const getToken = vi.fn().mockResolvedValue('context-token')
    const transport = new WebSocketTransport({
      endpoint: socket.url,
      getToken,
      platformId: 'platform-1',
      agentId: 'agent-7',
      user: { id: 'user-9', displayName: 'Alice' },
      websocketFactory: () => socket
    })

    const connecting = transport.connect()
    socket.open()
    await Promise.resolve()

    expect(getToken).toHaveBeenCalledWith({
      platformId: 'platform-1',
      agentId: 'agent-7',
      user: { id: 'user-9', displayName: 'Alice' }
    })
    socket.receive(event(1, 'session_ready'))
    await connecting
  })

  it('re-registers in-memory tools after reconnecting', async () => {
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
      reconnect: { maxRetries: 1, delayMs: 10 }
    })
    transport.registerHostTools({
      type: 'host_tools_register',
      payload: {
        tools: [{ name: 'read_page', description: 'Read page', inputSchema: { type: 'object' } }]
      }
    })

    const connecting = transport.connect()
    sockets[0].open()
    await Promise.resolve()
    sockets[0].receive(event(1, 'session_ready'))
    await connecting
    expect(sockets[0].sent).toHaveLength(2)
    expect(JSON.parse(sockets[0].sent[1])).toMatchObject({
      type: 'host_tools_register',
      payload: { tools: [{ name: 'read_page' }] }
    })

    sockets[0].close(1006)
    await vi.advanceTimersByTimeAsync(10)
    sockets[1].open()
    await Promise.resolve()
    sockets[1].receive(event(2, 'session_ready'))
    expect(sockets[1].sent).toHaveLength(2)
    expect(JSON.parse(sockets[1].sent[1])).toMatchObject({
      type: 'host_tools_register',
      payload: { tools: [{ name: 'read_page' }] }
    })
    vi.useRealTimers()
  })

  it('rejects an empty token without sending an auth frame', async () => {
    const socket = new FakeWebSocket('wss://agent.test/ws')
    const transport = new WebSocketTransport({
      endpoint: socket.url,
      getToken: vi.fn().mockResolvedValue('  '),
      platformId: 'p',
      agentId: 'a',
      websocketFactory: () => socket
    })

    const connecting = transport.connect()
    socket.open()

    await expect(connecting).rejects.toThrow('token provider returned an empty token')
    expect(socket.sent).toEqual([])
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

  it('includes the server conversation id on subsequent chat messages', async () => {
    const socket = new FakeWebSocket('wss://agent.test/ws')
    const transport = new WebSocketTransport({
      endpoint: socket.url,
      getToken: vi.fn().mockResolvedValue('token'),
      platformId: 'p',
      agentId: 'a',
      websocketFactory: () => socket
    })
    const connected = transport.connect()
    socket.open()
    await Promise.resolve()
    socket.receive(event(1, 'session_ready', { sessionId: 'conversation-42' }))
    await connected

    transport.send({ type: 'message_send', requestId: 'req-2', payload: { text: '继续' } })

    expect(JSON.parse(socket.sent[1])).toMatchObject({
      type: 'message_send',
      conversationId: 'conversation-42',
      payload: { text: '继续' }
    })
  })

  it('reconnects with exponential backoff after an unexpected close', async () => {
    vi.useFakeTimers()
    const sockets: FakeWebSocket[] = []
    const getToken = vi.fn().mockResolvedValue('token')
    const transport = new WebSocketTransport({
      endpoint: 'wss://agent.test/ws',
      getToken,
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
    sockets[1].open()
    await Promise.resolve()
    expect(getToken).toHaveBeenCalledTimes(2)
    vi.useRealTimers()
  })

  it('binds native timer methods to the global receiver during reconnect', async () => {
    const nativeSetTimeout = function (
      this: typeof globalThis,
      callback: TimerHandler,
      delay?: number
    ) {
      if (this !== globalThis) throw new TypeError('Illegal invocation')
      return globalThis.setTimeout(callback, delay)
    }
    const socket = new FakeWebSocket('wss://agent.test/ws')
    const transport = new WebSocketTransport({
      endpoint: socket.url,
      getToken: vi.fn().mockResolvedValue('token'),
      platformId: 'p',
      agentId: 'a',
      websocketFactory: () => socket,
      setTimeout: nativeSetTimeout,
      reconnect: { maxRetries: 1, delayMs: 1 }
    })
    const connected = transport.connect()
    socket.open()
    await Promise.resolve()
    socket.receive(event(1, 'session_ready'))
    await connected

    expect(() => socket.close(1006)).not.toThrow()
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
