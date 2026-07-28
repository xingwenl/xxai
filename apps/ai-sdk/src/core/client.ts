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
import { SSETransport } from './transport'
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
  private pendingAssistantMessage: { id: string; text: string } | null = null
  private pendingCitations: unknown[] = []
  private uiMounted = false
  private uiContainer: HTMLElement | null = null

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

    this.transport =
      this.options.transport === 'sse'
        ? new SSETransport()
        : new WebSocketTransport({
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
              knowledgeGrounded: msg.payload.knowledgeGrounded
            }
          }
          this.messageStore.addMessage(message)
          this.pendingAssistantMessage = null
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
  }

  registerTools(tools: ToolDefinition[]): void {
    this.toolRegistry.registerTools(tools)
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
