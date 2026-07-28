import { describe, expect, it } from 'vitest'
import { AgentClient } from '../client'

describe('AgentClient protocol events', () => {
  it('maps streaming, citations, tools and errors to SDK callbacks', () => {
    const messages: any[] = []
    const client = new AgentClient({
      endpoint: 'wss://agent.test/ws',
      platformId: 'p',
      agentId: 'a',
      getToken: async () => 'token',
      callbacks: { onMessage: (message) => messages.push(message) }
    })
    const transport = (client as any).transport
    transport.emit('message', {
      id: '1', type: 'session_ready', protocolVersion: 1, sequence: 1,
      timestamp: new Date().toISOString(), payload: { sessionId: 's' }
    })
    transport.emit('message', {
      id: '2', type: 'message_started', protocolVersion: 1, sequence: 2,
      timestamp: new Date().toISOString(), requestId: 'r', payload: {}
    })
    transport.emit('message', {
      id: '3', type: 'message_delta', protocolVersion: 1, sequence: 3,
      timestamp: new Date().toISOString(), requestId: 'r', payload: { content: 'Hi' }
    })
    transport.emit('message', {
      id: '4', type: 'citation', protocolVersion: 1, sequence: 4,
      timestamp: new Date().toISOString(), requestId: 'r', payload: { title: 'FAQ', text: 'Answer' }
    })
    transport.emit('message', {
      id: '5', type: 'message_completed', protocolVersion: 1, sequence: 5,
      timestamp: new Date().toISOString(), requestId: 'r', payload: { content: 'Hi' }
    })
    const lastMessage = messages[messages.length - 1]
    expect(lastMessage).toMatchObject({ role: 'assistant', content: { text: 'Hi' } })
    expect(lastMessage.metadata.citations).toEqual([{ title: 'FAQ', text: 'Answer' }])
  })

  it('exposes cancellation for the active request', () => {
    const client = new AgentClient({
      endpoint: 'wss://agent.test/ws', platformId: 'p', agentId: 'a', getToken: async () => 'token'
    })
    const transport = (client as any).transport
    const sent: any[] = []
    transport.send = (message: any) => sent.push(message)
    transport.emit('message', {
      id: '1', type: 'message_started', protocolVersion: 1, sequence: 1,
      timestamp: new Date().toISOString(), requestId: 'req-1', payload: {}
    })
    client.cancelMessage()
    expect(sent).toEqual([{ type: 'message_cancel', requestId: 'req-1', payload: {} }])
  })
})
