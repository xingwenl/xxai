import { describe, expect, it } from 'vitest'

import { PROTOCOL_VERSION, SDK_VERSION, parseProtocolEvent } from '../protocol'

// 与后端 tests/gateway/test_event_parity.py 共用同一份 golden：
// 后端保证「SSE 与 WS 两个编码器产出这批信封」，SDK 保证「这批信封都能被解析」。
import goldenEvents from './fixtures/run-events.golden.json'
import packageJson from '../../../package.json'

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

  it('parses MCP confirmation metadata without exposing credentials', () => {
    const event = parseProtocolEvent({
      id: 'evt_confirm',
      type: 'confirmation_required',
      protocolVersion: 1,
      sequence: 6,
      timestamp: new Date().toISOString(),
      payload: {
        callId: 'call_mcp_1',
        name: 'orders.cancel',
        toolType: 'mcp_tool',
        sideEffect: 'write',
        summary: { arguments: { orderId: 'o-1' } },
        expiresAt: '2026-08-07T12:00:00Z'
      }
    })

    expect(event.payload).toMatchObject({
      callId: 'call_mcp_1',
      toolType: 'mcp_tool',
      summary: { arguments: { orderId: 'o-1' } }
    })
  })

  it('normalizes unknown event types so old SDKs can ignore them', () => {
    const event = parseProtocolEvent({
      id: 'evt_future',
      type: 'future_agent_event',
      protocolVersion: 1,
      sequence: 5,
      timestamp: new Date().toISOString(),
      payload: {}
    })

    expect(event.type).toBe('unknown')
  })

  it('parses structured questions with options and free text flag', () => {
    const event = parseProtocolEvent({
      id: 'evt_q',
      type: 'question_required',
      protocolVersion: 1,
      sequence: 7,
      timestamp: new Date().toISOString(),
      payload: {
        questionId: 'q_1',
        question: '如何处理重复订单？',
        description: '发现两条相同订单',
        options: [
          { id: 'skip', label: '跳过' },
          { id: 'merge', label: '合并' }
        ],
        allowFreeText: true,
        requireSelection: true,
        expiresAt: '2026-08-24T12:00:00Z'
      }
    })

    expect(event.type).toBe('question_required')
    expect(event.payload).toMatchObject({
      questionId: 'q_1',
      question: '如何处理重复订单？',
      options: [
        { id: 'skip', label: '跳过' },
        { id: 'merge', label: '合并' }
      ],
      allowFreeText: true
    })
  })
})

describe('shared run-event golden', () => {
  it('reports the package version instead of a hardcoded literal', () => {
    expect(SDK_VERSION).toBe(packageJson.version)
  })

  it('parses every golden envelope without falling back to unknown', () => {
    const parsed = goldenEvents.map((envelope) => parseProtocolEvent(envelope))

    expect(goldenEvents.length).toBeGreaterThanOrEqual(18)
    expect(parsed.map((event) => event.type)).toEqual(
      goldenEvents.map((envelope) => envelope.type)
    )
    expect(parsed.every((event) => event.type !== 'unknown')).toBe(true)
    expect(parsed.every((event) => event.protocolVersion === PROTOCOL_VERSION)).toBe(true)
  })

  it('keeps camelCase envelope keys and usage on message_completed', () => {
    const completed = goldenEvents.find((envelope) => envelope.type === 'message_completed')
    expect(completed).toBeDefined()

    const event = parseProtocolEvent(completed)
    expect(event.conversationId).toBe('101')
    expect(event.requestId).toBe('req-golden')
    expect(event.payload).toMatchObject({
      knowledgeGrounded: true,
      usage: { total_tokens: 15 }
    })
  })

  it('reads tool call and tool result payloads by name', () => {
    const call = parseProtocolEvent(
      goldenEvents.find((envelope) => envelope.type === 'tool_call')
    )
    const result = parseProtocolEvent(
      goldenEvents.find((envelope) => envelope.type === 'tool_result')
    )

    expect(call.payload).toEqual({
      name: 'http_get',
      input: 'GET https://example.com',
      callId: 'call_1'
    })
    expect(result.payload).toMatchObject({ name: 'http_get', status: 'completed' })
  })
})
