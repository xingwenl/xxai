import { describe, expect, it } from 'vitest'
import { AgentClient } from '../client'

describe('replayed assistant events', () => {
  it('materializes a completed message when message_started was not replayed', () => {
    const client = new AgentClient({
      endpoint: 'wss://agent.test/ws',
      platformId: 'p',
      agentId: 'a',
      getToken: async () => 'token'
    })
    const transport = (client as any).transport

    transport.emit('message', {
      id: '1', type: 'message_completed', protocolVersion: 1, sequence: 8,
      timestamp: new Date().toISOString(), conversationId: '42', requestId: 'r1',
      payload: { content: '恢复后的回答' }
    })

    expect(client.getMessages()).toHaveLength(1)
    expect((client.getMessages()[0].content as { type: 'text'; text: string }).text).toBe('恢复后的回答')
  })

  it('accumulates replayed deltas before the completion event', () => {
    const client = new AgentClient({
      endpoint: 'wss://agent.test/ws',
      platformId: 'p',
      agentId: 'a',
      getToken: async () => 'token'
    })
    const transport = (client as any).transport

    transport.emit('message', {
      id: '1', type: 'message_delta', protocolVersion: 1, sequence: 6,
      timestamp: new Date().toISOString(), conversationId: '42', requestId: 'r1',
      payload: { content: '恢复' }
    })
    transport.emit('message', {
      id: '2', type: 'message_delta', protocolVersion: 1, sequence: 7,
      timestamp: new Date().toISOString(), conversationId: '42', requestId: 'r1',
      payload: { content: '内容' }
    })
    transport.emit('message', {
      id: '3', type: 'message_completed', protocolVersion: 1, sequence: 8,
      timestamp: new Date().toISOString(), conversationId: '42', requestId: 'r1',
      payload: { content: '恢复内容' }
    })

    expect((client.getMessages()[0].content as { type: 'text'; text: string }).text).toBe('恢复内容')
  })

  it('does not clear an in-progress message when replay repeats message_started', () => {
    const client = new AgentClient({
      endpoint: 'wss://agent.test/ws',
      platformId: 'p',
      agentId: 'a',
      getToken: async () => 'token'
    })
    const transport = (client as any).transport
    const base = { protocolVersion: 1, timestamp: new Date().toISOString(), requestId: 'r1', payload: {} }

    transport.emit('message', { ...base, id: '1', type: 'message_started', sequence: 1 })
    transport.emit('message', { ...base, id: '2', type: 'message_delta', sequence: 2, payload: { content: '断线前' } })
    transport.emit('message', { ...base, id: '3', type: 'message_started', sequence: 3 })
    transport.emit('message', { ...base, id: '4', type: 'message_delta', sequence: 4, payload: { content: '恢复后' } })
    transport.emit('message', { ...base, id: '5', type: 'message_completed', sequence: 5, payload: { content: '断线前恢复后' } })

    expect((client.getMessages()[0].content as { type: 'text'; text: string }).text).toBe('断线前恢复后')
  })
})
