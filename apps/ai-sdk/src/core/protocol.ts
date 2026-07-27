export const PROTOCOL_VERSION = 1 as const

export type ProtocolEventType =
  | 'session_ready'
  | 'message_started'
  | 'message_delta'
  | 'citation'
  | 'message_completed'
  | 'tool_call'
  | 'tool_result'
  | 'error'
  | 'pong'

export interface ErrorPayload {
  code: string
  message: string
  retryable: boolean
  details?: Record<string, string>
}

export type ProtocolPayload =
  | Record<string, never>
  | { content: string }
  | { title: string; text: string; sourceUrl?: string }
  | { name: string; status: string }
  | ErrorPayload

export interface ProtocolEvent {
  id: string
  type: ProtocolEventType
  protocolVersion: typeof PROTOCOL_VERSION
  conversationId?: string
  requestId?: string
  sequence: number
  timestamp: string
  payload: ProtocolPayload
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function parseProtocolEvent(input: unknown): ProtocolEvent {
  if (!isObject(input)) {
    throw new Error('Invalid protocol event')
  }

  if (input.protocolVersion !== PROTOCOL_VERSION) {
    throw new Error('Unsupported protocol version')
  }

  const required = ['id', 'type', 'sequence', 'timestamp', 'payload']
  if (
    required.some((field) => !(field in input)) ||
    typeof input.id !== 'string' ||
    typeof input.type !== 'string' ||
    typeof input.sequence !== 'number' ||
    typeof input.timestamp !== 'string' ||
    !isObject(input.payload)
  ) {
    throw new Error('Invalid protocol event')
  }

  const eventTypes: ProtocolEventType[] = [
    'session_ready',
    'message_started',
    'message_delta',
    'citation',
    'message_completed',
    'tool_call',
    'tool_result',
    'error',
    'pong'
  ]
  if (!eventTypes.includes(input.type as ProtocolEventType)) {
    throw new Error(`Unknown protocol event: ${input.type}`)
  }

  return {
    id: input.id,
    type: input.type as ProtocolEventType,
    protocolVersion: PROTOCOL_VERSION,
    ...(typeof input.conversationId === 'string'
      ? { conversationId: input.conversationId }
      : {}),
    ...(typeof input.requestId === 'string' ? { requestId: input.requestId } : {}),
    sequence: input.sequence,
    timestamp: input.timestamp,
    payload: input.payload as ProtocolPayload
  }
}
