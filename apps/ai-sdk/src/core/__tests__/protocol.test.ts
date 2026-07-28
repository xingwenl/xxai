import { describe, expect, it } from 'vitest'

import { parseProtocolEvent } from '../protocol'

describe('protocol v1', () => {
  it('parses a message delta and ignores unknown optional fields', () => {
    const event = parseProtocolEvent({
      id: 'evt_01',
      type: 'message_delta',
      protocolVersion: 1,
      sequence: 3,
      timestamp: '2026-07-27T00:00:00Z',
      payload: { content: '你好' },
      futureField: 'ignored'
    })

    expect(event.type).toBe('message_delta')
    expect(event.protocolVersion).toBe(1)
    expect(event.payload).toEqual({ content: '你好' })
  })

  it('rejects an unknown protocol major version', () => {
    expect(() =>
      parseProtocolEvent({
        id: 'evt_01',
        type: 'message_delta',
        protocolVersion: 2,
        sequence: 1,
        timestamp: '2026-07-27T00:00:00Z',
        payload: { content: 'x' }
      })
    ).toThrow('Unsupported protocol version')
  })

  it('rejects events without required envelope fields', () => {
    expect(() =>
      parseProtocolEvent({
        id: 'evt_01',
        type: 'message_delta',
        protocolVersion: 1,
        sequence: 1,
        payload: { content: 'x' }
      })
    ).toThrow('Invalid protocol event')
  })

  it('parses host tool calls', () => {
    const event = parseProtocolEvent({
      id: 'evt_host',
      type: 'host_tool_call',
      protocolVersion: 1,
      sequence: 4,
      timestamp: new Date().toISOString(),
      payload: {
        callId: 'call_123456',
        name: 'orders.get_status',
        arguments: { orderId: 'o-1' },
        sideEffect: 'none',
        requiresConfirmation: false
      }
    })

    expect(event.type).toBe('host_tool_call')
    expect(event.payload).toMatchObject({ callId: 'call_123456' })
  })
})
