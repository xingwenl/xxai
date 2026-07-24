import type {
  ConnectionState,
  OutgoingMessage,
  WebSocketMessage
} from './types'
import { EventEmitter } from './event-emitter'
import type { Transport } from './transport'

export class WebSocketTransport extends EventEmitter implements Transport {
  private _ws: WebSocket | null = null
  private _state: ConnectionState = 'disconnected'
  private _reconnectAttempts = 0
  private _maxRetries: number
  private _reconnectDelay: number
  private _endpoint: string
  private _getToken: () => Promise<string>
  private _platformId: string
  private _agentId: string
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private _messageId = 0

  constructor(options: {
    endpoint: string
    getToken: () => Promise<string>
    platformId: string
    agentId: string
    reconnect?: { maxRetries?: number; delayMs?: number }
  }) {
    super()
    this._endpoint = options.endpoint
    this._getToken = options.getToken
    this._platformId = options.platformId
    this._agentId = options.agentId
    this._maxRetries = options.reconnect?.maxRetries ?? 5
    this._reconnectDelay = options.reconnect?.delayMs ?? 3000
  }

  get state(): ConnectionState {
    return this._state
  }

  private setState(state: ConnectionState): void {
    if (this._state !== state) {
      this._state = state
      this.emit('state', state)
    }
  }

  private generateId(): string {
    return `msg_${++this._messageId}_${Date.now()}`
  }

  async connect(): Promise<void> {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      return
    }

    this.setState('connecting')

    try {
      // Mock WebSocket 连接，用于演示
      this.connectMock()
    } catch (error) {
      this.setState('error')
      this.emit('error', error)
      throw error
    }
  }

  private connectMock(): void {
    // Mock WebSocket 实现
    this.setState('connected')
    this.emit('open')

    // Mock 回复
    setTimeout(() => {
      const mockMessage: WebSocketMessage = {
        id: this.generateId(),
        type: 'session_ready',
        timestamp: new Date().toISOString(),
        payload: {
          sessionId: 'mock_session_123'
        }
      }
      this.handleMessage(mockMessage)
    }, 500)
  }

  private handleMessage(data: WebSocketMessage): void {
    this.emit('message', data)
  }

  send(message: OutgoingMessage): void {
    if (this._state !== 'connected') {
      console.warn('WebSocket not connected, cannot send message')
      return
    }

    const wsMessage: WebSocketMessage = {
      id: this.generateId(),
      type: message.type,
      timestamp: new Date().toISOString(),
      payload: message.payload
    }

    // Mock 发送，直接触发回复
    if (message.type === 'message_send') {
      this.mockReply(wsMessage)
    }

    console.log('Mock sending message:', wsMessage)
  }

  private mockReply(requestMessage: WebSocketMessage): void {
    setTimeout(() => {
      const responseId = this.generateId()

      // 回复开始
      this.handleMessage({
        id: responseId,
        type: 'message_started',
        requestId: requestMessage.id,
        timestamp: new Date().toISOString(),
        payload: {}
      })

      // 流式文本
      const text = (requestMessage.payload.text as string) || 'Hello'
      const chunks = text.split('')
      let delay = 100

      chunks.forEach((char, i) => {
        setTimeout(() => {
          this.handleMessage({
            id: `${responseId}_delta_${i}`,
            type: 'text_delta',
            requestId: requestMessage.id,
            timestamp: new Date().toISOString(),
            payload: {
              text: char
            }
          })
        }, delay)
        delay += 50
      })

      // 回复完成
      setTimeout(() => {
        this.handleMessage({
          id: `${responseId}_completed`,
          type: 'message_completed',
          requestId: requestMessage.id,
          timestamp: new Date().toISOString(),
          payload: {
            text: text.toUpperCase()
          }
        })
      }, delay + 100)
    }, 300)
  }

  disconnect(): void {
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer)
      this._reconnectTimer = null
    }

    if (this._ws) {
      this._ws.close()
      this._ws = null
    }

    this.setState('disconnected')
    this.emit('close')
  }

  override on(
    event: 'message' | 'open' | 'close' | 'error' | 'state',
    handler: (...args: any[]) => void
  ): void {
    super.on(event, handler)
  }

  override off(
    event: 'message' | 'open' | 'close' | 'error' | 'state',
    handler: (...args: any[]) => void
  ): void {
    super.off(event, handler)
  }
}
