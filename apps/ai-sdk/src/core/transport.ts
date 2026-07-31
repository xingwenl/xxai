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
