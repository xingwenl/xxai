export const PROTOCOL_VERSION = 1 as const
export const SDK_VERSION = '0.1.0' as const

export type ProtocolEventType =
  | 'session_ready'
  | 'message_started'
  | 'message_delta'
  | 'citation'
  | 'message_completed'
  | 'tool_call'
  | 'tool_result'
  | 'host_tool_call'
  | 'confirmation_required'
  | 'error'
  | 'pong'
  | 'agent_loop_started'
  | 'agent_step_started'
  | 'agent_step_delta'
  | 'agent_step_completed'
  | 'agent_loop_completed'
  | 'unknown'

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
  | { callId: string; name: string; arguments: unknown; sideEffect?: string; requiresConfirmation?: boolean }
  | {
      callId: string
      name: string
      toolType?: 'mcp_tool' | 'host_tool'
      sideEffect?: 'none' | 'navigation' | 'write' | 'financial' | 'external'
      summary?: Record<string, unknown>
      expiresAt?: string
    }
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
    'host_tool_call',
    'confirmation_required',
    'error',
    'pong',
    'agent_loop_started',
    'agent_step_started',
    'agent_step_delta',
    'agent_step_completed',
    'agent_loop_completed'
  ]
  const knownType = eventTypes.includes(input.type as ProtocolEventType)

  return {
    id: input.id,
    type: knownType ? input.type as ProtocolEventType : 'unknown',
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
