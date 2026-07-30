import { describe, expect, it, vi } from 'vitest'
import { FakeWebSocket } from '../../test/fake-websocket'
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
      sdkVersion: '0.1.0'
    })
    socket.receive(ready({ serverVersion: '0.1.0', minimumSdkVersion: '0.1.0', capabilities: ['replay'] }))
    await connecting
    expect(transport.serverCapabilities).toEqual(['replay'])
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

    await expect(connecting).rejects.toThrow('unsupported_sdk_version')
    expect(errors).toEqual([{ code: 'unsupported_sdk_version', retryable: false }])
    expect(JSON.stringify(errors)).not.toContain('private-token')
  })
})
