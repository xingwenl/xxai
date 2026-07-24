import type { ConnectionState, OutgoingMessage } from './types'

export interface Transport {
  connect(): Promise<void>
  disconnect(): void
  send(message: OutgoingMessage): void
  on(
    event: 'message' | 'open' | 'close' | 'error',
    handler: (...args: any[]) => void
  ): void
  off(
    event: 'message' | 'open' | 'close' | 'error',
    handler: (...args: any[]) => void
  ): void
  get state(): ConnectionState
}

// SSE 传输层预留实现
export class SSETransport implements Transport {
  get state(): ConnectionState {
    return 'disconnected'
  }

  async connect(): Promise<void> {
    throw new Error('SSETransport not implemented yet')
  }

  disconnect(): void {
    throw new Error('SSETransport not implemented yet')
  }

  send(_message: OutgoingMessage): void {
    throw new Error('SSETransport not implemented yet')
  }

  on(
    _event: 'message' | 'open' | 'close' | 'error',
    _handler: (...args: any[]) => void
  ): void {
    // Placeholder
  }

  off(
    _event: 'message' | 'open' | 'close' | 'error',
    _handler: (...args: any[]) => void
  ): void {
    // Placeholder
  }
}
