import packageJson from '../../package.json'

export const PROTOCOL_VERSION = 1 as const
// 单一来源：SDK 版本号直接取自 package.json，避免与产物版本漂移。
// 网关的兼容矩阵会比对这里上报的版本，写死字面量会让上报不可信。
export const SDK_VERSION: string = packageJson.version

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
  | 'question_required'
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
  // 工具调用通知：client 读 payload.name / payload.input。
  | { name: string; input?: unknown; callId?: string }
  // 工具执行结果：client 读 payload.name / payload.result。
  | { name: string; result?: unknown; status?: string; error?: unknown }
  | { callId: string; name: string; arguments: unknown; sideEffect?: string; requiresConfirmation?: boolean }
  | {
      callId: string
      name: string
      toolType?: 'mcp_tool' | 'host_tool'
      sideEffect?: 'none' | 'navigation' | 'write' | 'financial' | 'external'
      summary?: Record<string, unknown>
      expiresAt?: string
    }
  | {
      questionId: string
      question: string
      description?: string
      options: { id: string; label: string }[]
      allowFreeText: boolean
      requireSelection?: boolean
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
    'question_required',
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
