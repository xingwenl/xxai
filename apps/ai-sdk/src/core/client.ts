import type {
  AgentCallbacks,
  AgentClientOptions,
  ConnectionState,
  AgentLoopRun,
  AgentLoopStep,
  AssistantTimelineEntry,
  Message,
  OutgoingMessage,
  ToolDefinition,
  ToolConfirmation,
  WebSocketMessage
} from './types'
import { EventEmitter } from './event-emitter'
import { MessageStore } from './message-store'
import { ToolRegistry } from './tool-registry'
import { WebSocketTransport } from './websocket'
import type { Transport } from './transport'
import { createPageTools } from './page/tools'

let messageId = 0
function generateId(): string {
  return `msg_${++messageId}_${Date.now()}`
}

export class AgentClient {
  private options: AgentClientOptions
  private transport: Transport
  private eventEmitter: EventEmitter
  private messageStore: MessageStore
  private toolRegistry: ToolRegistry
  private _systemPrompt: string | undefined
  private _callbacks: AgentCallbacks = {}
  private conversationId: string | undefined
  private currentRequestId: string | undefined
  private activeRequestId: string | undefined
  private pendingAssistantMessage: { id: string; text: string; timeline?: AssistantTimelineEntry[]; loop?: AgentLoopRun } | null = null
  private pendingCitations: unknown[] = []
  private uiMounted = false
  private uiContainer: HTMLElement | null = null
  private pendingConfirmations = new Set<string>()
  private pendingHostCalls = new Map<string, { name: string; arguments: unknown }>()
  private pendingLoop: AgentLoopRun | null = null
  readonly storageKey: string

  constructor(options: AgentClientOptions) {
    this.options = {
      ...options,
      ui: {
        mode: 'floating',
        position: 'right',
        theme: 'auto',
        locale: 'zh-CN',
        ...options.ui
      },
      transport: options.transport || 'websocket',
      reconnect: {
        maxRetries: 5,
        delayMs: 3000,
        ...options.reconnect
      }
    }

    this._systemPrompt = options.systemPrompt
    this.storageKey = options.storageKey || `xxai-agent:${options.platformId}:${options.agentId}:${options.user?.id || 'anonymous'}`
    this.eventEmitter = new EventEmitter()
    const persisted = this.readPersistedState()
    this.conversationId = persisted?.conversationId
    this.messageStore = new MessageStore(persisted?.messages || options.messages || [])
    this.toolRegistry = new ToolRegistry()
    this._callbacks = options.callbacks || {}

    this.transport = new WebSocketTransport({
      endpoint: this.options.endpoint,
      getToken: this.options.getToken,
      platformId: this.options.platformId,
      agentId: this.options.agentId,
      user: this.options.user,
      reconnect: this.options.reconnect,
      conversationId: this.conversationId
    })

    if (options.pageTools?.enabled) {
      this.registerTools(createPageTools(options.pageTools))
    }

    this.setupTransportListeners()
    this.persistState()
  }

  private setupTransportListeners(): void {
    if (this.transport instanceof WebSocketTransport) {
      this.transport.on('state', (state: ConnectionState) => {
        this.handleConnectionStateChange(state)
      })
    }

    this.transport.on('open', () => {
      console.log('Connection opened')
    })

    this.transport.on('message', (msg: WebSocketMessage) => {
      this.handleTransportMessage(msg)
    })

    this.transport.on('close', () => {
      console.log('Connection closed')
    })

    this.transport.on('error', (error: Error) => {
      console.error('Connection error:', error)
      this.handleRequestError({
        code: 'agent_connection_failed',
        message: 'Agent 连接失败，本轮对话已结束',
        retryable: true,
        details: { error: error.message }
      })
    })
  }

  private handleConnectionStateChange(state: ConnectionState): void {
    this._callbacks.onConnectionState?.(state)
    this.eventEmitter.emit('connection_state', state)
  }

  private handleTransportMessage(msg: WebSocketMessage): void {
    // 网关在每个会话事件的顶层返回 conversationId；同步到 Client，保证
    // UI 消息、宿主工具上下文和后续重连看到的是同一个会话标识。
    if (typeof msg.conversationId === 'string' && msg.conversationId) {
      console.info('[xxai-agent][conversation] client synchronized conversation id', {
        eventType: msg.type,
        requestId: msg.requestId,
        previousConversationId: this.conversationId,
        conversationId: msg.conversationId
      })
      this.conversationId = msg.conversationId
      this.persistState()
    }
    let message: Message | null = null

    switch (msg.type) {
      case 'session_ready':
        if (typeof msg.payload.sessionId === 'string' && msg.payload.sessionId) {
          this.conversationId = msg.payload.sessionId
          this.persistState()
        }
        break
      case 'message_started':
        this.currentRequestId = msg.requestId
        this.activeRequestId = msg.requestId
        this.pendingAssistantMessage = {
          id: generateId(),
          text: '',
          timeline: [],
          loop: this.pendingLoop || undefined
        }
        this.pendingCitations = []
        this.updatePendingMessage()
        break
      case 'agent_loop_started':
        this.pendingLoop = {
          id: String(msg.payload.loopRunId || msg.payload.id || msg.requestId || generateId()),
          requestId: String(msg.requestId || ''),
          status: 'running',
          summary: typeof msg.payload.summary === 'string' ? msg.payload.summary : undefined,
          steps: []
        }
        if (this.pendingAssistantMessage) this.pendingAssistantMessage.loop = this.pendingLoop
        this.eventEmitter.emit('agent_loop', this.pendingLoop)
        this.updatePendingMessage()
        break
      case 'agent_step_started':
      case 'agent_step_completed': {
        if (!this.pendingLoop) {
          this.pendingLoop = {
            id: String(msg.payload.loopRunId || msg.payload.id || msg.requestId || generateId()),
            requestId: String(msg.requestId || ''),
            status: 'running',
            steps: []
          }
        }
        const step = this.mergeLoopStep(msg)
        const index = this.pendingLoop.steps.findIndex((item) => item.id === step.id)
        if (index === -1) this.pendingLoop.steps.push(step)
        else this.pendingLoop.steps[index] = { ...this.pendingLoop.steps[index], ...step }
        this.upsertTimelineStep(step.id)
        this.eventEmitter.emit('agent_loop', { ...this.pendingLoop, steps: [...this.pendingLoop.steps] })
        this.pendingAssistantMessage && (this.pendingAssistantMessage.loop = this.pendingLoop)
        this.updatePendingMessage()
        break
      }
      case 'agent_step_delta': {
        if (!this.pendingLoop) break
        const payload = msg.payload as Record<string, unknown>
        const content = typeof payload.content === 'string' ? payload.content : ''
        if (payload.field !== 'thinking' || !content) break
        const stepId = typeof payload.stepId === 'string' ? payload.stepId : ''
        let index = this.pendingLoop.steps.findIndex((item) => item.id === stepId)
        if (index === -1) {
          index = this.pendingLoop.steps.findIndex(
            (item) => item.stepType === 'model_generation' || item.stepType === 'thinking'
          )
        }
        if (index === -1) break
        const step = this.pendingLoop.steps[index]
        this.pendingLoop.steps[index] = {
          ...step,
          thinkingText: (step.thinkingText || '') + content
        }
        this.eventEmitter.emit('agent_loop', { ...this.pendingLoop, steps: [...this.pendingLoop.steps] })
        this.pendingAssistantMessage && (this.pendingAssistantMessage.loop = this.pendingLoop)
        this.updatePendingMessage()
        break
      }
      case 'agent_loop_completed':
        if (this.pendingLoop) {
          this.pendingLoop = {
            ...this.pendingLoop,
            status: (msg.payload.status as AgentLoopRun['status']) || 'completed',
            summary: typeof msg.payload.summary === 'string' ? msg.payload.summary : this.pendingLoop.summary
          }
          this.eventEmitter.emit('agent_loop', this.pendingLoop)
          this.pendingAssistantMessage && (this.pendingAssistantMessage.loop = this.pendingLoop)
          this.updatePendingMessage()
        }
        break
      case 'message_delta':
        if (this.pendingAssistantMessage) {
          const delta = (msg.payload.content as string) || ''
          this.pendingAssistantMessage.text += delta
          this.appendTimelineText(delta)
          this.updatePendingMessage()
        }
        break
      case 'citation':
        this.pendingCitations.push(msg.payload)
        this.eventEmitter.emit('citation', msg.payload)
        break
      case 'tool_call':
        this._callbacks.onToolCall?.(msg.payload.name as string, msg.payload.input)
        this.eventEmitter.emit('tool_call', msg.payload)
        break
      case 'tool_result':
        this._callbacks.onToolResult?.(msg.payload.name as string, msg.payload.result)
        this.eventEmitter.emit('tool_result', msg.payload)
        break
      case 'host_tool_call':
        void this.executeHostTool(msg)
        break
      case 'confirmation_required':
        this.pendingConfirmations.add(String(msg.payload.callId))
        const confirmation: ToolConfirmation = {
          callId: String(msg.payload.callId),
          name: String(msg.payload.name),
          toolType: msg.payload.toolType as ToolConfirmation['toolType'],
          sideEffect: msg.payload.sideEffect as ToolConfirmation['sideEffect'],
          summary: msg.payload.summary as Record<string, unknown> | undefined,
          expiresAt: typeof msg.payload.expiresAt === 'string' ? msg.payload.expiresAt : undefined
        }
        this._callbacks.onConfirmationRequired?.(confirmation)
        this.eventEmitter.emit('confirmation_required', confirmation)
        break
      case 'message_completed':
        if (this.pendingAssistantMessage) {
          const finalText = (msg.payload.content as string) || this.pendingAssistantMessage.text
          const completedLoop = msg.payload.loop as AgentLoopRun | undefined
          const loop = completedLoop && this.pendingLoop
            ? { ...this.pendingLoop, ...completedLoop, steps: completedLoop.steps?.length ? completedLoop.steps : this.pendingLoop.steps }
            : completedLoop || this.pendingLoop || undefined
          const timeline = this.pendingAssistantMessage.timeline?.length
            ? this.pendingAssistantMessage.timeline
            : finalText
              ? [{ kind: 'text' as const, id: `${this.pendingAssistantMessage.id}_text`, text: finalText }]
              : undefined
          message = {
            id: this.pendingAssistantMessage.id,
            role: 'assistant',
            type: 'text',
            content: {
              type: 'text',
              text: finalText
            },
            contentBlocks: Array.isArray(msg.payload.contentBlocks)
              ? msg.payload.contentBlocks as Message['contentBlocks']
              : [{ id: `${this.pendingAssistantMessage.id}_text`, type: 'markdown', text: finalText, status: 'completed' }],
            timeline,
            loop,
            timestamp: new Date(),
            conversationId: this.conversationId,
            requestId: this.currentRequestId,
            metadata: {
              citations: this.pendingCitations,
              knowledgeGrounded: msg.payload.knowledgeGrounded,
              ...(msg.payload.usage ? { usage: msg.payload.usage } : {})
            }
          }
          this.messageStore.addMessage(message)
          this.persistState()
          this.pendingAssistantMessage = null
          this.activeRequestId = undefined
          this.pendingCitations = []
          this.pendingLoop = null
        }
        break
      case 'error':
        this.handleRequestError(
          msg.payload as Record<string, unknown>,
          msg.requestId
        )
        break
      default:
        console.log('Unhandled message type:', msg.type)
    }

    if (message) {
      this._callbacks.onMessage?.(message)
      this.eventEmitter.emit('message', message)
    }
  }

  private updatePendingMessage(): void {
    if (this.pendingAssistantMessage) {
      // 这里可以触发 UI 更新
      this.eventEmitter.emit('message_updating', {
        id: this.pendingAssistantMessage.id,
        text: this.pendingAssistantMessage.text,
        timeline: this.pendingAssistantMessage.timeline,
        loop: this.pendingAssistantMessage.loop
      })
    }
  }

  private appendTimelineText(text: string): void {
    if (!this.pendingAssistantMessage || !text) return
    const timeline = this.pendingAssistantMessage.timeline || (this.pendingAssistantMessage.timeline = [])
    const last = timeline[timeline.length - 1]
    if (last && last.kind === 'text') {
      last.text += text
    } else {
      timeline.push({ kind: 'text', id: generateId(), text })
    }
  }

  private upsertTimelineStep(stepId: string): void {
    if (!this.pendingAssistantMessage || !stepId) return
    const timeline = this.pendingAssistantMessage.timeline || (this.pendingAssistantMessage.timeline = [])
    if (!timeline.some((entry) => entry.kind === 'step' && entry.stepId === stepId)) {
      timeline.push({ kind: 'step', id: generateId(), stepId })
    }
  }

  private handleRequestError(
    errorPayload: Record<string, unknown>,
    requestId?: string
  ): void {
    const errorText = String(errorPayload.message || errorPayload.code || '请求失败')
    const activeRequestId = requestId || this.currentRequestId || this.activeRequestId
    const failedLoop = this.pendingLoop
      ? {
          ...this.pendingLoop,
          status: 'failed' as const,
          summary: errorText,
          steps: this.pendingLoop.steps.map((step) =>
            step.status === 'running'
              ? { ...step, status: 'failed' as const, error: errorPayload }
              : step
          )
        }
      : undefined
    if (failedLoop) this.eventEmitter.emit('agent_loop', failedLoop)

    if (activeRequestId || this.pendingAssistantMessage) {
      const messageId = this.pendingAssistantMessage?.id || generateId()
      const failedMessage: Message = {
        id: messageId,
        role: 'assistant',
        type: 'error',
        content: { type: 'text', text: errorText },
        contentBlocks: [{
          id: `${messageId}_error`,
          type: 'error',
          text: errorText,
          status: 'failed',
          metadata: { error: errorPayload }
        }],
        loop: failedLoop,
        timestamp: new Date(),
        conversationId: this.conversationId,
        requestId: activeRequestId,
        metadata: { error: errorPayload }
      }
      this.messageStore.addMessage(failedMessage)
      this.persistState()
      this._callbacks.onMessage?.(failedMessage)
      this.eventEmitter.emit('message', failedMessage)
    }

    this.pendingAssistantMessage = null
    this.pendingLoop = null
    this.pendingCitations = []
    this.currentRequestId = undefined
    this.activeRequestId = undefined
    this._callbacks.onError?.(new Error(errorText))
    this.eventEmitter.emit('error', errorPayload)
  }

  private mergeLoopStep(msg: WebSocketMessage): AgentLoopStep {
    const payload = msg.payload
    return {
      id: String(payload.stepId || payload.id || generateId()),
      sequence: Number(payload.sequence || msg.sequence || 0),
      stepType: String(payload.stepType || 'thinking'),
      title: String(payload.title || '处理中'),
      status: (payload.status as AgentLoopStep['status']) || 'running',
      inputSummary: typeof payload.inputSummary === 'string' ? payload.inputSummary : undefined,
      outputSummary: typeof payload.outputSummary === 'string' ? payload.outputSummary : undefined,
      thinkingText: typeof payload.thinkingText === 'string' ? payload.thinkingText : undefined,
      toolName: typeof payload.toolName === 'string' ? payload.toolName : undefined,
      skillName: typeof payload.skillName === 'string' ? payload.skillName : undefined,
      skillVersion: typeof payload.skillVersion === 'string' ? payload.skillVersion : undefined,
      citationRefs: Array.isArray(payload.citationRefs) ? payload.citationRefs : undefined,
      error: payload.error && typeof payload.error === 'object' ? payload.error as Record<string, unknown> : undefined,
      durationMs: typeof payload.durationMs === 'number' ? payload.durationMs : undefined
    }
  }

  async connect(): Promise<void> {
    await this.transport.connect()
  }

  disconnect(): void {
    this.transport.disconnect()
    this.clearPendingConfirmations()
  }

  get connectionState(): ConnectionState {
    return this.transport.state
  }

  open(): void {
    this.eventEmitter.emit('ui_open')
  }

  close(): void {
    this.eventEmitter.emit('ui_close')
  }

  toggle(): void {
    this.eventEmitter.emit('ui_toggle')
  }

  destroy(): void {
    this.disconnect()
    this.eventEmitter.emit('ui_destroy')
    this.eventEmitter.removeAllListeners()
    this.messageStore.clearMessages()
    this.toolRegistry.clearCustomTools()
    this.clearPendingConfirmations()

    if (this.uiContainer && this.uiMounted) {
      this.uiContainer.remove()
      this.uiContainer = null
      this.uiMounted = false
    }
  }

  async sendMessage(text: string): Promise<void> {
    const userMessage: Message = {
      id: generateId(),
      role: 'user',
      type: 'text',
      content: {
        type: 'text',
        text: text
      },
      timestamp: new Date(),
      conversationId: this.conversationId
    }

    this.messageStore.addMessage(userMessage)
    this.persistState()
    this._callbacks.onMessage?.(userMessage)
    this.eventEmitter.emit('message', userMessage)

    const outgoing: OutgoingMessage = {
      type: 'message_send',
      requestId: generateId(),
      payload: {
        text,
        ...(this._systemPrompt ? { systemPrompt: this._systemPrompt } : {})
      }
    }

    this.currentRequestId = outgoing.requestId
    this.activeRequestId = outgoing.requestId
    this.transport.send(outgoing)
  }

  cancelMessage(): void {
    if (!this.activeRequestId) return
    this.transport.send({
      type: 'message_cancel',
      requestId: this.activeRequestId,
      payload: {}
    })
    this.activeRequestId = undefined
    this.pendingAssistantMessage = null
    this.eventEmitter.emit('message_cancelled')
  }

  getMessages(): Message[] {
    return this.messageStore.getMessages()
  }

  addMessage(message: Message): void {
    this.messageStore.addMessage(message)
    this.persistState()
    this._callbacks.onMessage?.(message)
    this.eventEmitter.emit('message', message)
  }

  clearMessages(): void {
    this.messageStore.clearMessages()
    this.pendingAssistantMessage = null
  }

  clearLocalHistory(): void {
    this.cancelMessage()
    this.messageStore.clearMessages()
    this.pendingAssistantMessage = null
    this.pendingLoop = null
    this.pendingCitations = []
    this.conversationId = undefined
    if (this.transport instanceof WebSocketTransport) this.transport.setConversationId(undefined)
    try {
      globalThis.localStorage?.removeItem(this.storageKey)
    } catch {
      // 浏览器禁用存储时保持内存状态可用。
    }
    this.eventEmitter.emit('history_cleared')
  }

  registerTool(tool: ToolDefinition): void {
    this.toolRegistry.registerTool(tool)
    if (this.transport instanceof WebSocketTransport) {
      const { execute: _execute, outputSchema: _outputSchema, timeoutMs: _timeoutMs, ...definition } = tool
      this.transport.registerHostTools({
        type: 'host_tools_register',
        payload: {
          tools: [definition]
        }
      })
    }
  }

  registerTools(tools: ToolDefinition[]): void {
    this.toolRegistry.registerTools(tools)
    if (this.transport instanceof WebSocketTransport) {
      this.transport.registerHostTools({
        type: 'host_tools_register',
        payload: {
          tools: tools.map(({ execute: _execute, outputSchema: _outputSchema, timeoutMs: _timeoutMs, sideEffect, ...baseDefinition }) => (
            { ...baseDefinition, ...(sideEffect ? { sideEffect } : {}) }
          )),
        }
      })
    }
  }

  unregisterTool(name: string): void {
    this.toolRegistry.unregisterTool(name)
  }

  getTool(name: string): ToolDefinition | undefined {
    return this.toolRegistry.getTool(name)
  }

  getToolNames(): string[] {
    return this.toolRegistry.getToolNames()
  }

  clearCustomTools(): void {
    this.toolRegistry.clearCustomTools()
  }

  resolveToolCall(callId: string, approved: boolean): void {
    if (!this.pendingConfirmations.has(callId)) return
    this.pendingConfirmations.delete(callId)
    const pending = this.pendingHostCalls.get(callId)
    if (this.transport instanceof WebSocketTransport) {
      this.transport.resolveToolCall(callId, approved)
    }
    if (approved && pending) void this.runHostTool(callId, pending.name, pending.arguments)
    if (!approved) this.pendingHostCalls.delete(callId)
    this.eventEmitter.emit('confirmation_resolved', { callId, approved })
  }

  private clearPendingConfirmations(): void {
    for (const callId of this.pendingConfirmations) {
      this.eventEmitter.emit('confirmation_resolved', { callId, approved: false })
    }
    this.pendingConfirmations.clear()
    this.pendingHostCalls.clear()
  }

  private async executeHostTool(msg: WebSocketMessage): Promise<void> {
    const callId = String(msg.payload.callId || '')
    const name = String(msg.payload.name || '')
    const tool = this.toolRegistry.getTool(name)
    if (!callId || !tool) {
      this.sendHostToolError(callId, 'host_tool_not_registered', 'Host tool is not registered')
      return
    }
    try {
      this.toolRegistry.validate(name, msg.payload.arguments)
      if (msg.payload.requiresConfirmation) {
        this.pendingConfirmations.add(callId)
        this.pendingHostCalls.set(callId, { name, arguments: msg.payload.arguments })
        const confirmation: ToolConfirmation = {
          callId,
          name,
          toolType: 'host_tool',
          sideEffect: msg.payload.sideEffect as ToolConfirmation['sideEffect'],
          summary: { arguments: msg.payload.arguments as unknown },
        }
        this._callbacks.onConfirmationRequired?.(confirmation)
        this.eventEmitter.emit('confirmation_required', confirmation)
        return
      }
      await this.runHostTool(callId, name, msg.payload.arguments)
    } catch (error) {
      this.sendHostToolError(callId, 'host_tool_arguments_invalid', error instanceof Error ? error.message : 'Invalid arguments')
    }
  }

  private async runHostTool(callId: string, name: string, params: unknown): Promise<void> {
    const tool = this.toolRegistry.getTool(name)
    if (!tool) return
    const timeout = tool.timeoutMs ?? 10000
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeout)
    try {
      const result = await tool.execute(params, { conversationId: this.conversationId, requestId: callId, signal: controller.signal } as any)
      const encoded = JSON.stringify(result)
      if (encoded.length > 32 * 1024) throw new Error('host_tool_result_too_large')
      if (this.transport instanceof WebSocketTransport) this.transport.sendHostToolResult(callId, result)
    } catch (error) {
      this.sendHostToolError(callId, 'host_tool_execution_failed', error instanceof Error ? error.message : 'Tool execution failed')
    } finally {
      clearTimeout(timer)
      this.pendingHostCalls.delete(callId)
    }
  }

  private sendHostToolError(callId: string, code: string, message: string): void {
    if (this.transport instanceof WebSocketTransport) this.transport.sendHostToolError(callId, code, message)
  }

  setSystemPrompt(prompt: string): void {
    this._systemPrompt = prompt
  }

  private readPersistedState(): { messages: Message[]; conversationId?: string } | null {
    try {
      const raw = globalThis.localStorage?.getItem(this.storageKey)
      if (!raw) return null
      const value = JSON.parse(raw) as { version?: number; messages?: Message[]; conversationId?: string }
      if (value.version !== 1 || !Array.isArray(value.messages)) {
        globalThis.localStorage?.removeItem(this.storageKey)
        return null
      }
      const messages = value.messages.filter((message) => message && typeof message.id === 'string').map((message) => ({
        ...message,
        timestamp: new Date(message.timestamp)
      }))
      return { messages, conversationId: typeof value.conversationId === 'string' ? value.conversationId : undefined }
    } catch {
      try {
        globalThis.localStorage?.removeItem(this.storageKey)
      } catch {
        // 存储整体不可用时无需继续处理损坏缓存。
      }
      return null
    }
  }

  private persistState(): void {
    try {
      globalThis.localStorage?.setItem(this.storageKey, JSON.stringify({
        version: 1,
        conversationId: this.conversationId,
        messages: this.messageStore.getMessages()
      }))
    } catch {
      // 浏览器禁用或超出容量时降级为内存消息。
    }
  }

  getSystemPrompt(): string | undefined {
    return this._systemPrompt
  }

  get callbacks(): AgentCallbacks {
    return this._callbacks
  }

  set callbacks(callbacks: AgentCallbacks) {
    this._callbacks = callbacks
  }

  on(event: string, handler: (...args: any[]) => void): void {
    this.eventEmitter.on(event, handler)
  }

  off(event: string, handler: (...args: any[]) => void): void {
    this.eventEmitter.off(event, handler)
  }

  // UI 相关方法，供 UI 层调用
  _setUIMounted(mounted: boolean): void {
    this.uiMounted = mounted
  }

  _setUIContainer(container: HTMLElement | null): void {
    this.uiContainer = container
  }

  _getEventEmitter(): EventEmitter {
    return this.eventEmitter
  }

  _getMessageStore(): MessageStore {
    return this.messageStore
  }
}
