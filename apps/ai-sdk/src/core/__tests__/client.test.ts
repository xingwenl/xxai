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
      timestamp: new Date().toISOString(), requestId: 'r', payload: {
        content: 'Hi',
        usage: { prompt_tokens: 12, completion_tokens: 4, total_tokens: 16 }
      }
    })
    const lastMessage = messages[messages.length - 1]
    expect(lastMessage).toMatchObject({ role: 'assistant', content: { text: 'Hi' } })
    expect(lastMessage.metadata.citations).toEqual([{ title: 'FAQ', text: 'Answer' }])
    expect(lastMessage.metadata.usage).toEqual({ prompt_tokens: 12, completion_tokens: 4, total_tokens: 16 })
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

  it('keeps streamed AgentLoop steps when completion only carries a summary', () => {
    const client = new AgentClient({ endpoint: 'wss://agent.test/ws', platformId: 'p', agentId: 'a', getToken: async () => 'token' })
    const transport = (client as any).transport
    transport.emit('message', { id: '1', type: 'agent_loop_started', protocolVersion: 1, sequence: 1, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1', summary: '处理中' } })
    transport.emit('message', { id: '2', type: 'agent_step_completed', protocolVersion: 1, sequence: 2, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1', stepId: 'step-1', sequence: 1, stepType: 'knowledge_retrieval', title: '检索知识库', status: 'succeeded' } })
    transport.emit('message', { id: '3', type: 'message_started', protocolVersion: 1, sequence: 3, timestamp: new Date().toISOString(), requestId: 'r', payload: {} })
    transport.emit('message', { id: '4', type: 'message_completed', protocolVersion: 1, sequence: 4, timestamp: new Date().toISOString(), requestId: 'r', payload: { content: '完成', loop: { id: 'loop-1', requestId: 'r', status: 'completed', summary: '已完成回答', steps: [] } } })
    expect((client as any).messageStore.getMessages()[0].loop.steps).toHaveLength(1)
  })

  it('publishes live loop steps with the pending assistant update', () => {
    const updates: any[] = []
    const client = new AgentClient({ endpoint: 'wss://agent.test/ws', platformId: 'p', agentId: 'a', getToken: async () => 'token' })
    client.on('message_updating', (update) => updates.push(update))
    const transport = (client as any).transport
    transport.emit('message', { id: '1', type: 'message_started', protocolVersion: 1, sequence: 1, timestamp: new Date().toISOString(), requestId: 'r', payload: {} })
    transport.emit('message', { id: '2', type: 'agent_loop_started', protocolVersion: 1, sequence: 2, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1', summary: '正在处理请求' } })
    transport.emit('message', { id: '3', type: 'agent_step_started', protocolVersion: 1, sequence: 3, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1', stepId: 'step-1', sequence: 1, stepType: 'host_tool', title: '调用工具：天气', status: 'running', toolName: 'weather' } })

    expect(updates[updates.length - 1]).toMatchObject({ text: '', loop: { id: 'loop-1', status: 'running', steps: [{ status: 'running', toolName: 'weather' }] } })
  })

  it('keeps loop state visible when loop events arrive before message_started', () => {
    const updates: any[] = []
    const client = new AgentClient({ endpoint: 'wss://agent.test/ws', platformId: 'p', agentId: 'a', getToken: async () => 'token' })
    client.on('message_updating', (update) => updates.push(update))
    const transport = (client as any).transport

    transport.emit('message', { id: '1', type: 'agent_loop_started', protocolVersion: 1, sequence: 1, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1', summary: '正在处理请求' } })
    transport.emit('message', { id: '2', type: 'message_started', protocolVersion: 1, sequence: 2, timestamp: new Date().toISOString(), requestId: 'r', payload: {} })
    transport.emit('message', { id: '3', type: 'agent_step_started', protocolVersion: 1, sequence: 3, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1', stepId: 'step-1', sequence: 1, stepType: 'model_generation', title: '生成回答', status: 'running' } })

    expect(updates[updates.length - 1]).toMatchObject({ loop: { id: 'loop-1', steps: [{ stepType: 'model_generation', status: 'running' }] } })
  })

  it('registers tools without requiring a client-side temporary mode', () => {
    const client = new AgentClient({
      endpoint: 'wss://agent.test/ws',
      platformId: 'p',
      agentId: 'a',
      getToken: async () => 'token',
    })
    const transport = (client as any).transport
    const registrations: any[] = []
    transport.registerHostTools = (message: any) => registrations.push(message)

    client.registerTools([
      {
        name: 'read_page',
        description: 'Read page',
        inputSchema: { type: 'object' },
        execute: async () => ({ ok: true })
      }
    ])

    expect(registrations[0]).toMatchObject({
      type: 'host_tools_register',
      payload: { tools: [{ name: 'read_page' }] }
    })
    expect(registrations[0].payload.temporary).toBeUndefined()
  })
})
