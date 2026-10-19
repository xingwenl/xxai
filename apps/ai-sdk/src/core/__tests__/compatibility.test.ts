import { describe, expect, it, vi } from 'vitest'
import { FakeWebSocket } from '../../test/fake-websocket'
import { SDK_VERSION } from '../protocol'
import { WebSocketTransport } from '../websocket'

const ready = (payload: Record<string, unknown> = {}) => ({
  id: 'evt-1',
  type: 'session_ready',
  protocolVersion: 1,
  sequence: 1,
  timestamp: new Date().toISOString(),
  payload
})

describe('SDK protocol compatibility', () => {
  it('sends SDK version and protocol version during auth', async () => {
    const socket = new FakeWebSocket('wss://agent.test/ws')
    const transport = new WebSocketTransport({
      endpoint: socket.url,
      getToken: vi.fn().mockResolvedValue('token'),
      platformId: 'p',
      agentId: 'a',
      websocketFactory: () => socket
    })
    const connecting = transport.connect()

    socket.open()
    await Promise.resolve()
    expect(JSON.parse(socket.sent[0]).payload).toMatchObject({
      protocolVersion: 1,
      sdkVersion: SDK_VERSION
    })
    expect(JSON.parse(socket.sent[0]).payload).not.toHaveProperty('capabilities')
    socket.receive(ready({ serverVersion: '0.1.0', minimumSdkVersion: '0.1.0' }))
    await connecting
    expect(transport.state).toBe('connected')
  })

  it('emits a structured compatibility error without exposing the token', async () => {
    const socket = new FakeWebSocket('wss://agent.test/ws')
    const transport = new WebSocketTransport({
      endpoint: socket.url,
      getToken: vi.fn().mockResolvedValue('private-token'),
      platformId: 'p',
      agentId: 'a',
      websocketFactory: () => socket
    })
    const errors: unknown[] = []
    transport.on('compatibility_error', (error) => errors.push(error))
    const connecting = transport.connect()
    socket.open()
    await Promise.resolve()
    socket.receive({
      ...ready(),
      type: 'error',
      payload: { code: 'unsupported_sdk_version', message: 'upgrade SDK', retryable: false }
    })

    await expect(connecting).rejects.toThrow('upgrade SDK')
    expect(errors).toHaveLength(1)
    const failure = errors[0] as Error & { code?: string; retryable?: boolean }
    expect(failure).toBeInstanceOf(Error)
    expect(failure.code).toBe('unsupported_sdk_version')
    expect(failure.retryable).toBe(false)
    expect(JSON.stringify(errors)).not.toContain('private-token')
  })

  it('treats the 4406 close as terminal and does not schedule a reconnect', async () => {
    const sockets: FakeWebSocket[] = []
    const factory = (url: string) => {
      const socket = new FakeWebSocket(url)
      sockets.push(socket)
      return socket
    }
    const transport = new WebSocketTransport({
      endpoint: 'wss://agent.test/ws',
      getToken: vi.fn().mockResolvedValue('token'),
      platformId: 'p',
      agentId: 'a',
      reconnect: { maxRetries: 3, delayMs: 1 },
      websocketFactory: factory
    })
    const errors: unknown[] = []
    transport.on('compatibility_error', (error) => errors.push(error))
    const connecting = transport.connect()
    sockets[0].open()
    await Promise.resolve()
    // 服务端先发 error 帧、再以 4406 关闭。
    sockets[0].receive({
      ...ready(),
      type: 'error',
      payload: {
        code: 'unsupported_protocol_version',
        message: '协议主版本不支持',
        retryable: false
      }
    })
    sockets[0].close(4406)

    await expect(connecting).rejects.toThrow('协议主版本不支持')
    expect(errors).toHaveLength(1)
    expect(transport.state).toBe('error')
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(sockets).toHaveLength(1)
  })

  it('reports a compatibility failure when the socket closes with 4406 alone', async () => {
    const sockets: FakeWebSocket[] = []
    const factory = (url: string) => {
      const socket = new FakeWebSocket(url)
      sockets.push(socket)
      return socket
    }
    const transport = new WebSocketTransport({
      endpoint: 'wss://agent.test/ws',
      getToken: vi.fn().mockResolvedValue('token'),
      platformId: 'p',
      agentId: 'a',
      reconnect: { maxRetries: 3, delayMs: 1 },
      websocketFactory: factory
    })
    const errors: unknown[] = []
    transport.on('compatibility_error', (error) => errors.push(error))
    const connecting = transport.connect()
    sockets[0].open()
    await Promise.resolve()
    // 缺子协议时服务端在 accept 之前就以 4406 关闭，发不出 error 帧。
    sockets[0].close(4406)

    await expect(connecting).rejects.toThrow('protocol_negotiation_failed')
    expect(errors).toHaveLength(1)
    expect((errors[0] as Error & { code?: string }).code).toBe('protocol_negotiation_failed')
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(sockets).toHaveLength(1)
  })
})
