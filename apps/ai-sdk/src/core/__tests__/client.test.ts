import { describe, expect, it, vi } from 'vitest'
import { AgentClient } from '../client'

describe('AgentClient protocol events', () => {
  it('uses explicit baseUrl for HTTP asset uploads instead of the WebSocket endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ data: { assetId: 'asset-1', filename: 'a.txt', mimeType: 'text/plain', size: 1, status: 'uploaded' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new AgentClient({
      endpoint: 'ws://127.0.0.1:8000/api/v1/ws/agents/1',
      baseUrl: 'http://127.0.0.1:8000/api/v1',
      platformId: 'p',
      agentId: '1',
      getToken: async () => 'token'
    })

    await client.uploadAsset(new File(['a'], 'a.txt', { type: 'text/plain' }))

    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/v1/embed/assets',
      expect.objectContaining({ method: 'POST' })
    )
    vi.unstubAllGlobals()
  })

  it('derives the legacy HTTP base URL from an agent WebSocket endpoint when baseUrl is omitted', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ data: { assetId: 'asset-1', filename: 'a.txt', mimeType: 'text/plain', size: 1, status: 'uploaded' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new AgentClient({
      endpoint: 'ws://127.0.0.1:8000/api/v1/ws/agents/1',
      platformId: 'p',
      agentId: '1',
      getToken: async () => 'token'
    })

    await client.uploadAsset(new File(['a'], 'a.txt', { type: 'text/plain' }))

    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/v1/embed/assets',
      expect.objectContaining({ method: 'POST' })
    )
    vi.unstubAllGlobals()
  })

  it('uploads into the current conversation when conversationId already exists', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ data: { assetId: 'asset-2', filename: 'b.jpg', mimeType: 'image/jpeg', size: 1, status: 'ready' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new AgentClient({
      endpoint: 'ws://127.0.0.1:8000/api/v1/ws/agents/1',
      baseUrl: 'http://127.0.0.1:8000/api/v1',
      platformId: 'p', agentId: '1', getToken: async () => 'token'
    })
    ;(client as any).conversationId = '232'

    await client.uploadAsset(new File(['b'], 'b.jpg', { type: 'image/jpeg' }))

    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/v1/embed/conversations/232/assets',
      expect.objectContaining({ method: 'POST' })
    )
    vi.unstubAllGlobals()
  })

  it('synchronizes the auto-created conversation with the WebSocket transport', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ data: {
        assetId: 'asset-first', filename: 'first.jpg', mimeType: 'image/jpeg',
        size: 1, status: 'ready', conversationId: 232
      } })
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new AgentClient({
      endpoint: 'ws://127.0.0.1:8000/api/v1/ws/agents/1',
      baseUrl: 'http://127.0.0.1:8000/api/v1',
      platformId: 'p', agentId: '1', getToken: async () => 'token'
    })

    await client.uploadAsset(new File(['a'], 'first.jpg', { type: 'image/jpeg' }))

    expect((client as any).conversationId).toBe('232')
    expect((client as any).transport._conversationId).toBe('232')
    vi.unstubAllGlobals()
  })

  it('恢复并持久化本地消息和会话，并可清空开启新会话', () => {
    const storage = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key)
    })
    const options = {
      endpoint: 'wss://agent.test/ws', platformId: 'p', agentId: 'a',
      user: { id: 'u' }, getToken: async () => 'token', storageKey: 'test-history'
    }
    const first = new AgentClient(options)
    ;(first as any).conversationId = '42'
    first.addMessage({ id: 'm1', role: 'user', type: 'text', content: { type: 'text', text: '你好' }, timestamp: new Date() })
    const second = new AgentClient(options)
    expect(second.getMessages()).toHaveLength(1)
    expect((second as any).conversationId).toBe('42')
    second.clearLocalHistory()
    expect(second.getMessages()).toEqual([])
    expect(storage.has('test-history')).toBe(false)
    vi.unstubAllGlobals()
  })

  it('发送消息时携带 systemPrompt', async () => {
    const client = new AgentClient({
      endpoint: 'wss://agent.test/ws', platformId: 'p', agentId: 'a',
      getToken: async () => 'token', systemPrompt: '用中文回答'
    })
    const sent: any[] = []
    ;(client as any).transport.send = (message: any) => sent.push(message)
    await client.sendMessage('测试')
    expect(sent[0].payload).toMatchObject({ text: '测试', systemPrompt: '用中文回答' })
  })

  it('发送带附件的消息时在用户消息中保留图片引用', async () => {
    const client = new AgentClient({
      endpoint: 'wss://agent.test/ws',
      baseUrl: 'https://api.test/api/v1',
      platformId: 'p', agentId: 'a', getToken: async () => 'token'
    })
    const sent: any[] = []
    ;(client as any).transport.send = (message: any) => sent.push(message)

    await client.sendMessage('看下这个图片', {
      attachments: [{
        assetId: 'asset-1', filename: 'photo.jpg', mimeType: 'image/jpeg', size: 12,
        previewUrl: 'blob:https://app.test/preview-1'
      }]
    })

    expect(client.getMessages()[0].contentBlocks).toEqual([
      expect.objectContaining({ type: 'markdown', text: '看下这个图片' }),
      expect.objectContaining({
        type: 'image', assetId: 'asset-1', asset_id: 'asset-1',
        url: '/api/v1/assets/asset-1', previewUrl: 'blob:https://app.test/preview-1', alt: 'photo.jpg'
      })
    ])
    expect(sent[0].payload.attachments).toEqual([
      { assetId: 'asset-1', filename: 'photo.jpg', mimeType: 'image/jpeg', size: 12 }
    ])
  })

  it('同步服务端事件顶层的 conversationId 到客户端消息和工具上下文', () => {
    const client = new AgentClient({
      endpoint: 'wss://agent.test/ws', platformId: 'p', agentId: 'a', getToken: async () => 'token'
    })
    const transport = (client as any).transport
    transport.emit('message', {
      id: '1', type: 'message_started', protocolVersion: 1, sequence: 1,
      timestamp: new Date().toISOString(), conversationId: '42', requestId: 'r', payload: {}
    })

    expect((client as any).conversationId).toBe('42')
    expect((client as any).pendingAssistantMessage).toMatchObject({ id: expect.any(String) })
  })

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

  it('turns a terminal error event into a failed assistant message', () => {
    const messages: any[] = []
    const errors: Error[] = []
    const client = new AgentClient({
      endpoint: 'wss://agent.test/ws',
      platformId: 'p',
      agentId: 'a',
      getToken: async () => 'token',
      callbacks: {
        onMessage: (message) => messages.push(message),
        onError: (error) => errors.push(error)
      }
    })
    const transport = (client as any).transport
    transport.emit('message', {
      id: '1', type: 'message_started', protocolVersion: 1, sequence: 1,
      timestamp: new Date().toISOString(), requestId: 'r', payload: {}
    })
    transport.emit('message', {
      id: '2', type: 'agent_loop_started', protocolVersion: 1, sequence: 2,
      timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1' }
    })
    transport.emit('message', {
      id: '3', type: 'error', protocolVersion: 1, sequence: 3,
      timestamp: new Date().toISOString(), requestId: 'r', payload: {
        code: 'agent_upstream_unavailable',
        message: 'Agent 连接失败（HTTP 502），本轮对话已结束',
        retryable: true,
        details: { statusCode: '502' }
      }
    })

    expect(messages[0]).toMatchObject({
      type: 'error',
      content: { text: 'Agent 连接失败（HTTP 502），本轮对话已结束' },
      contentBlocks: [{ type: 'error', status: 'failed' }],
      loop: { id: 'loop-1', status: 'failed' }
    })
    expect(errors[0].message).toContain('HTTP 502')
    expect((client as any).pendingAssistantMessage).toBeNull()
    expect((client as any).activeRequestId).toBeUndefined()
  })

  it('ends a queued request when the transport fails before message_started', async () => {
    const messages: any[] = []
    const client = new AgentClient({
      endpoint: 'wss://agent.test/ws',
      platformId: 'p',
      agentId: 'a',
      getToken: async () => 'token',
      callbacks: { onMessage: (message) => messages.push(message) }
    })
    const transport = (client as any).transport

    await client.sendMessage('测试连接')
    transport.emit('error', new Error('WebSocket closed (4401)'))

    expect(messages).toHaveLength(2)
    expect(messages[1]).toMatchObject({
      role: 'assistant',
      type: 'error',
      content: { text: 'Agent 连接失败，本轮对话已结束' },
      contentBlocks: [{ type: 'error', status: 'failed' }]
    })
    expect((client as any).activeRequestId).toBeUndefined()
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

  it('keeps builtin tool step metadata in live loop updates', () => {
    const updates: any[] = []
    const client = new AgentClient({ endpoint: 'wss://agent.test/ws', platformId: 'p', agentId: 'a', getToken: async () => 'token' })
    client.on('message_updating', (update) => updates.push(update))
    const transport = (client as any).transport
    transport.emit('message', { id: '1', type: 'message_started', protocolVersion: 1, sequence: 1, timestamp: new Date().toISOString(), requestId: 'r', payload: {} })
    transport.emit('message', { id: '2', type: 'agent_loop_started', protocolVersion: 1, sequence: 2, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1' } })
    transport.emit('message', { id: '3', type: 'agent_step_started', protocolVersion: 1, sequence: 3, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1', stepId: 'step-1', sequence: 1, stepType: 'builtin_tool', title: '调用工具：http_get', status: 'running', toolName: 'http_get' } })

    expect(updates[updates.length - 1]).toMatchObject({ loop: { steps: [{ stepType: 'builtin_tool', toolName: 'http_get' }] } })
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

  it('registers page tools only when explicitly enabled', () => {
    const disabled = new AgentClient({ endpoint: 'wss://agent.test/ws', platformId: 'p', agentId: 'a', getToken: async () => 'token' })
    expect(disabled.getToolNames().filter(name => name.startsWith('page_'))).toEqual([])

    const enabled = new AgentClient({ endpoint: 'wss://agent.test/ws', platformId: 'p', agentId: 'a', getToken: async () => 'token', pageTools: { enabled: true } })
    expect(enabled.getToolNames().filter(name => name.startsWith('page_'))).toEqual([
      'page_snapshot', 'page_click', 'page_type', 'page_scroll', 'page_wait', 'page_extract'
    ])
  })

  it('dispatches MCP confirmations and resolves each call only once', () => {
    const confirmations: any[] = []
    const events: any[] = []
    const client = new AgentClient({
      endpoint: 'wss://agent.test/ws', platformId: 'p', agentId: 'a', getToken: async () => 'token',
      callbacks: { onConfirmationRequired: (value) => confirmations.push(value) }
    })
    const transport = (client as any).transport
    const sent: any[] = []
    transport.resolveToolCall = (callId: string, approved: boolean) => sent.push({ callId, approved })
    client.on('confirmation_required', (value) => events.push(value))

    transport.emit('message', {
      id: 'confirm', type: 'confirmation_required', protocolVersion: 1, sequence: 1,
      timestamp: new Date().toISOString(), payload: {
        callId: 'mcp-call-1', name: 'orders.cancel', toolType: 'mcp_tool',
        sideEffect: 'write', summary: { arguments: { orderId: 'o-1' } },
        expiresAt: '2026-08-07T12:00:00Z'
      }
    })

    client.resolveToolCall('mcp-call-1', true)
    client.resolveToolCall('mcp-call-1', true)

    expect(confirmations[0]).toMatchObject({ toolType: 'mcp_tool', sideEffect: 'write' })
    expect(events[0]).toMatchObject({ callId: 'mcp-call-1', toolType: 'mcp_tool' })
    expect(sent).toEqual([{ callId: 'mcp-call-1', approved: true }])
  })

  it('dispatches structured questions and answers each question once', () => {
    const questions: any[] = []
    const events: any[] = []
    const resolved: any[] = []
    const client = new AgentClient({
      endpoint: 'wss://agent.test/ws', platformId: 'p', agentId: 'a', getToken: async () => 'token',
      callbacks: { onQuestionRequired: (value) => questions.push(value) }
    })
    const transport = (client as any).transport
    const sent: any[] = []
    transport.sendQuestionAnswer = (questionId: string, answer: unknown) =>
      sent.push({ questionId, answer })
    client.on('question_required', (value) => events.push(value))
    client.on('question_resolved', (value) => resolved.push(value))

    transport.emit('message', {
      id: 'q', type: 'question_required', protocolVersion: 1, sequence: 1,
      timestamp: new Date().toISOString(), payload: {
        questionId: 'q_1', question: '如何处理重复订单？',
        options: [{ id: 'skip', label: '跳过' }, { id: 'merge', label: '合并' }],
        allowFreeText: true
      }
    })

    expect(questions[0]).toMatchObject({ questionId: 'q_1', question: '如何处理重复订单？', allowFreeText: true })
    expect(events[0]).toMatchObject({ questionId: 'q_1', options: [{ id: 'skip', label: '跳过' }, { id: 'merge', label: '合并' }] })

    expect(client.answerQuestion('q_1', { selectedOptionId: 'merge' })).toBe(true)
    expect(client.answerQuestion('q_1', { selectedOptionId: 'merge' })).toBe(false)
    expect(sent).toEqual([{ questionId: 'q_1', answer: { selectedOptionId: 'merge' } }])
    expect(resolved[0]).toMatchObject({ questionId: 'q_1', answer: { selectedOptionId: 'merge' } })
  })

  it('maps inputSummary and thinkingText from step payloads', () => {
    const updates: any[] = []
    const client = new AgentClient({ endpoint: 'wss://agent.test/ws', platformId: 'p', agentId: 'a', getToken: async () => 'token' })
    client.on('message_updating', (update) => updates.push(update))
    const transport = (client as any).transport

    transport.emit('message', { id: '1', type: 'message_started', protocolVersion: 1, sequence: 1, timestamp: new Date().toISOString(), requestId: 'r', payload: {} })
    transport.emit('message', { id: '2', type: 'agent_loop_started', protocolVersion: 1, sequence: 2, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1' } })
    transport.emit('message', { id: '3', type: 'agent_step_started', protocolVersion: 1, sequence: 3, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1', stepId: 'gen-1', sequence: 1, stepType: 'model_generation', title: '生成回答', status: 'running' } })
    transport.emit('message', { id: '4', type: 'agent_step_started', protocolVersion: 1, sequence: 4, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1', stepId: 'tool-1', sequence: 2, stepType: 'mcp_tool', title: '调用工具：get_weather', status: 'running', toolName: 'get_weather', inputSummary: '{"city":"上海"}' } })

    const steps = updates[updates.length - 1].loop.steps
    expect(steps.find((s: any) => s.id === 'tool-1')).toMatchObject({ inputSummary: '{"city":"上海"}' })
  })

  it('appends agent_step_delta thinking content to the generation step', () => {
    const updates: any[] = []
    const client = new AgentClient({ endpoint: 'wss://agent.test/ws', platformId: 'p', agentId: 'a', getToken: async () => 'token' })
    client.on('message_updating', (update) => updates.push(update))
    const transport = (client as any).transport

    transport.emit('message', { id: '1', type: 'message_started', protocolVersion: 1, sequence: 1, timestamp: new Date().toISOString(), requestId: 'r', payload: {} })
    transport.emit('message', { id: '2', type: 'agent_loop_started', protocolVersion: 1, sequence: 2, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1' } })
    transport.emit('message', { id: '3', type: 'agent_step_started', protocolVersion: 1, sequence: 3, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1', stepId: 'gen-1', sequence: 1, stepType: 'model_generation', title: '生成回答', status: 'running' } })
    transport.emit('message', { id: '4', type: 'agent_step_delta', protocolVersion: 1, sequence: 4, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1', stepId: 'gen-1', stepType: 'model_generation', field: 'thinking', content: '先分析' } })
    transport.emit('message', { id: '5', type: 'agent_step_delta', protocolVersion: 1, sequence: 5, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1', stepId: 'gen-1', stepType: 'model_generation', field: 'thinking', content: '再回答' } })

    const step = updates[updates.length - 1].loop.steps[0]
    expect(step).toMatchObject({ stepType: 'model_generation', thinkingText: '先分析再回答' })
  })

  it('builds a chronological timeline from deltas and steps', () => {
    const updates: any[] = []
    const client = new AgentClient({ endpoint: 'wss://agent.test/ws', platformId: 'p', agentId: 'a', getToken: async () => 'token' })
    client.on('message_updating', (update) => updates.push(update))
    const transport = (client as any).transport

    transport.emit('message', { id: '1', type: 'message_started', protocolVersion: 1, sequence: 1, timestamp: new Date().toISOString(), requestId: 'r', payload: {} })
    transport.emit('message', { id: '2', type: 'agent_step_started', protocolVersion: 1, sequence: 2, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1', stepId: 'gen-1', sequence: 1, stepType: 'model_generation', title: '生成回答', status: 'running' } })
    transport.emit('message', { id: '3', type: 'message_delta', protocolVersion: 1, sequence: 3, timestamp: new Date().toISOString(), requestId: 'r', payload: { content: '开头' } })
    transport.emit('message', { id: '4', type: 'agent_step_started', protocolVersion: 1, sequence: 4, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1', stepId: 'tool-1', sequence: 2, stepType: 'mcp_tool', title: '调用工具：get_weather', status: 'running', toolName: 'get_weather' } })
    transport.emit('message', { id: '5', type: 'message_delta', protocolVersion: 1, sequence: 5, timestamp: new Date().toISOString(), requestId: 'r', payload: { content: '结尾' } })

    const timeline = updates[updates.length - 1].timeline
    expect(timeline.map((entry: any) => entry.kind)).toEqual(['step', 'text', 'step', 'text'])
    const texts = timeline.filter((entry: any) => entry.kind === 'text')
    expect(texts.map((entry: any) => entry.text)).toEqual(['开头', '结尾'])
  })

  it('keeps the timeline on the completed message', () => {
    const messages: any[] = []
    const client = new AgentClient({
      endpoint: 'wss://agent.test/ws', platformId: 'p', agentId: 'a', getToken: async () => 'token',
      callbacks: { onMessage: (message) => messages.push(message) }
    })
    const transport = (client as any).transport

    transport.emit('message', { id: '1', type: 'message_started', protocolVersion: 1, sequence: 1, timestamp: new Date().toISOString(), requestId: 'r', payload: {} })
    transport.emit('message', { id: '2', type: 'agent_step_started', protocolVersion: 1, sequence: 2, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1', stepId: 'gen-1', sequence: 1, stepType: 'model_generation', title: '生成回答', status: 'running' } })
    transport.emit('message', { id: '3', type: 'message_delta', protocolVersion: 1, sequence: 3, timestamp: new Date().toISOString(), requestId: 'r', payload: { content: '回答内容' } })
    transport.emit('message', { id: '4', type: 'agent_step_completed', protocolVersion: 1, sequence: 4, timestamp: new Date().toISOString(), requestId: 'r', payload: { loopRunId: 'loop-1', stepId: 'gen-1', sequence: 1, stepType: 'model_generation', title: '生成回答', status: 'succeeded', outputSummary: '生成 4 字符', thinkingText: '思考全文' } })
    transport.emit('message', { id: '5', type: 'message_completed', protocolVersion: 1, sequence: 5, timestamp: new Date().toISOString(), requestId: 'r', payload: { content: '回答内容', loop: { id: 'loop-1', requestId: 'r', status: 'completed', summary: '已完成回答', steps: [] } } })

    expect(messages[0].timeline).toEqual([
      { kind: 'step', id: expect.any(String), stepId: 'gen-1' },
      { kind: 'text', id: expect.any(String), text: '回答内容' }
    ])
    expect(messages[0].loop.steps[0]).toMatchObject({ thinkingText: '思考全文' })
  })

  it('解析 session_ready 下发的 client/agent/quota 并触发 client_info 事件', () => {
    const events: any[] = []
    const client = new AgentClient({
      endpoint: 'wss://agent.test/ws', platformId: 'p', agentId: 'a', getToken: async () => 'token'
    })
    client.on('client_info', (info) => events.push(info))
    const transport = (client as any).transport

    transport.emit('message', {
      id: '1', type: 'session_ready', protocolVersion: 1, sequence: 1,
      timestamp: new Date().toISOString(), payload: {
        sessionId: 's',
        client: { clientId: 'client_1', name: 'ToolVerse', tokenTtlSeconds: 600, maxTokensPerMinute: 120, maxConnections: 50 },
        agent: { agentId: 11, name: '客服助手', slug: 'support-bot', description: '负责售后问题' },
        quota: {
          windowSeconds: 60,
          resources: {
            connection: { limit: 10, current: 2 },
            message: { limit: 60, current: 12 },
            model_tokens: { limit: 10000000, current: 123456 },
            token_issue: { limit: 120, current: 3 }
          }
        }
      }
    })

    expect(client.clientInfo).toEqual({ clientId: 'client_1', name: 'ToolVerse', tokenTtlSeconds: 600, maxTokensPerMinute: 120, maxConnections: 50 })
    expect(client.agentInfo).toEqual({ agentId: 11, name: '客服助手', slug: 'support-bot', description: '负责售后问题' })
    expect(client.quota?.resources?.model_tokens).toEqual({ limit: 10000000, current: 123456 })
    expect(events).toHaveLength(1)
    expect(events[0]).toMatchObject({
      client: { name: 'ToolVerse' },
      agent: { name: '客服助手' },
      quota: { windowSeconds: 60 }
    })
  })

  it('旧网关 session_ready 无新字段时 getter 保持 undefined', () => {
    const client = new AgentClient({
      endpoint: 'wss://agent.test/ws', platformId: 'p', agentId: 'a', getToken: async () => 'token'
    })
    const transport = (client as any).transport

    transport.emit('message', {
      id: '1', type: 'session_ready', protocolVersion: 1, sequence: 1,
      timestamp: new Date().toISOString(), payload: { sessionId: 's' }
    })

    expect(client.clientInfo).toBeUndefined()
    expect(client.agentInfo).toBeUndefined()
    expect(client.quota).toBeUndefined()
  })
  it('onError 与 on(\'error\') 收到同一个带错误码的 AgentError', async () => {
    const errors: any[] = []
    const events: any[] = []
    const client = new AgentClient({
      endpoint: 'wss://agent.test/ws',
      platformId: 'p',
      agentId: 'a',
      getToken: async () => 'token',
      callbacks: { onError: (error) => errors.push(error) }
    })
    client.on('error', (payload: any) => events.push(payload))
    const transport = (client as any).transport

    await client.sendMessage('触发失败')
    transport.emit('message', {
      id: '1', type: 'error', protocolVersion: 1, sequence: 1,
      timestamp: new Date().toISOString(), requestId: 'r', payload: {
        code: 'chat_model_unavailable',
        message: '对话模型不可用',
        retryable: false,
        details: { minimumSdkVersion: '0.1.0' }
      }
    })

    expect(errors).toHaveLength(1)
    expect(errors[0]).toBeInstanceOf(Error)
    expect(errors[0].code).toBe('chat_model_unavailable')
    expect(errors[0].retryable).toBe(false)
    expect(errors[0].details).toEqual({ minimumSdkVersion: '0.1.0' })
    // 同一个对象：调用方从两条路径拿到的错误形状一致。
    expect(events[0]).toBe(errors[0])
  })

  it('兼容性失败只上报一次（compatibility_error 与 error 成对发出时不重复）', async () => {
    const errors: any[] = []
    const client = new AgentClient({
      endpoint: 'wss://agent.test/ws',
      platformId: 'p',
      agentId: 'a',
      getToken: async () => 'token',
      callbacks: { onError: (error) => errors.push(error) }
    })
    const transport = (client as any).transport
    const failure: any = new Error('当前 SDK 版本过低，请升级到 0.2.0 或更高版本')
    failure.name = 'AgentError'
    failure.code = 'unsupported_sdk_version'
    failure.retryable = false

    transport.emit('compatibility_error', failure)
    transport.emit('error', failure)

    expect(errors).toHaveLength(1)
    expect(errors[0].code).toBe('unsupported_sdk_version')
  })
})
