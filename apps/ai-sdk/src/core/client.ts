import type {
  AgentCallbacks,
  AgentClientOptions,
  ConnectionState,
  Message,
  OutgoingMessage,
  ToolDefinition,
  WebSocketMessage
} from './types'
import { EventEmitter } from './event-emitter'
import { MessageStore } from './message-store'
import { ToolRegistry } from './tool-registry'
import { WebSocketTransport } from './websocket'
import type { Transport } from './transport'

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
  private pendingAssistantMessage: { id: string; text: string } | null = null
  private pendingCitations: unknown[] = []
  private uiMounted = false
  private uiContainer: HTMLElement | null = null
  private pendingConfirmations = new Set<string>()
  private pendingHostCalls = new Map<string, { name: string; arguments: unknown }>()

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
    this.eventEmitter = new EventEmitter()
    this.messageStore = new MessageStore(options.messages || [])
    this.toolRegistry = new ToolRegistry()
    this._callbacks = options.callbacks || {}

    this.transport = new WebSocketTransport({
      endpoint: this.options.endpoint,
      getToken: this.options.getToken,
      platformId: this.options.platformId,
      agentId: this.options.agentId,
      reconnect: this.options.reconnect
    })

    this.setupTransportListeners()
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
      this._callbacks.onError?.(error)
    })
  }

  private handleConnectionStateChange(state: ConnectionState): void {
    this._callbacks.onConnectionState?.(state)
    this.eventEmitter.emit('connection_state', state)
  }

  private handleTransportMessage(msg: WebSocketMessage): void {
    let message: Message | null = null

    switch (msg.type) {
      case 'session_ready':
        this.conversationId = msg.payload.sessionId as string
        break
      case 'message_started':
        this.currentRequestId = msg.requestId
        this.activeRequestId = msg.requestId
        this.pendingAssistantMessage = {
          id: generateId(),
          text: ''
        }
        this.pendingCitations = []
        break
      case 'message_delta':
        if (this.pendingAssistantMessage) {
          this.pendingAssistantMessage.text += (msg.payload.content as string) || ''
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
        this._callbacks.onConfirmationRequired?.({
          callId: String(msg.payload.callId),
          name: String(msg.payload.name),
          summary: msg.payload.summary as Record<string, unknown> | undefined
        })
        this.eventEmitter.emit('confirmation_required', msg.payload)
        break
      case 'message_completed':
        if (this.pendingAssistantMessage) {
          const finalText = (msg.payload.content as string) || this.pendingAssistantMessage.text
          message = {
            id: this.pendingAssistantMessage.id,
            role: 'assistant',
            type: 'text',
            content: {
              type: 'text',
              text: finalText
            },
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
          this.pendingAssistantMessage = null
          this.activeRequestId = undefined
          this.pendingCitations = []
        }
        break
      case 'error':
        this._callbacks.onError?.(new Error(String(msg.payload.message || msg.payload.code)))
        this.eventEmitter.emit('error', msg.payload)
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
        text: this.pendingAssistantMessage.text
      })
    }
  }

  async connect(): Promise<void> {
    await this.transport.connect()
  }

  disconnect(): void {
    this.transport.disconnect()
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
    this.pendingConfirmations.clear()
    this.pendingHostCalls.clear()

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
    this._callbacks.onMessage?.(userMessage)
    this.eventEmitter.emit('message', userMessage)

    const outgoing: OutgoingMessage = {
      type: 'message_send',
      requestId: generateId(),
      payload: {
        text: text
      }
    }

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
    this._callbacks.onMessage?.(message)
    this.eventEmitter.emit('message', message)
  }

  clearMessages(): void {
    this.messageStore.clearMessages()
    this.pendingAssistantMessage = null
  }

  registerTool(tool: ToolDefinition): void {
    this.toolRegistry.registerTool(tool)
    if (this.transport instanceof WebSocketTransport) {
      const { execute: _execute, outputSchema: _outputSchema, timeoutMs: _timeoutMs, sideEffect: _sideEffect, ...definition } = tool
      this.transport.registerHostTools({ type: 'host_tools_register', payload: { tools: [definition] } })
    }
  }

  registerTools(tools: ToolDefinition[]): void {
    this.toolRegistry.registerTools(tools)
    if (this.transport instanceof WebSocketTransport) {
      this.transport.registerHostTools({
        type: 'host_tools_register',
        payload: {
          tools: tools.map(({ execute: _execute, outputSchema: _outputSchema, timeoutMs: _timeoutMs, sideEffect: _sideEffect, ...tool }) => tool)
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
        this._callbacks.onConfirmationRequired?.({ callId, name, summary: { arguments: msg.payload.arguments } })
        this.eventEmitter.emit('confirmation_required', { callId, name })
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
