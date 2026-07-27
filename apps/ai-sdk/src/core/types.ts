export type ConnectionState =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'error'

export type MessageRole = 'user' | 'assistant' | 'system' | 'tool'

export type MessageType =
  | 'text'
  | 'message_delta'
  | 'tool_call'
  | 'tool_result'
  | 'citation'
  | 'error'
  | 'custom'

export interface TextContent {
  type: 'text'
  text: string
}

export interface ImageContent {
  type: 'image'
  url: string
  alt?: string
}

export interface ButtonContent {
  text: string
  value: string
  style?: 'primary' | 'secondary' | 'danger'
}

export interface TextWithButtonsContent {
  type: 'text_with_buttons'
  text: string
  buttons: ButtonContent[]
}

export interface CustomContent {
  type: 'custom'
  componentName: string
  props: Record<string, unknown>
}

export type MessageContent =
  | TextContent
  | ImageContent
  | TextWithButtonsContent
  | CustomContent

export interface Message {
  id: string
  role: MessageRole
  type: MessageType
  content: MessageContent
  timestamp: Date
  conversationId?: string
  requestId?: string
  metadata?: Record<string, unknown>
}

export interface ToolDefinition {
  name: string
  description: string
  inputSchema: Record<string, unknown>
  outputSchema?: Record<string, unknown>
  sideEffect?: 'none' | 'navigation' | 'write' | 'financial' | 'external'
  timeoutMs?: number
  execute: (params: unknown, context: ToolContext) => Promise<unknown>
}

export interface ToolContext {
  conversationId?: string
  requestId?: string
}

export interface UIOptions {
  mode: 'headless' | 'floating' | 'embedded'
  position?: 'left' | 'right'
  locale?: string
  theme?: 'light' | 'dark' | 'auto'
  container?: HTMLElement
}

export interface AgentCallbacks {
  onMessage?: (message: Message) => void
  onConnectionState?: (state: ConnectionState) => void
  onToolCall?: (name: string, input: unknown) => void
  onToolResult?: (name: string, result: unknown) => void
  onError?: (error: Error) => void
}

export interface AgentClientOptions {
  endpoint: string
  platformId: string
  agentId: string
  getToken: () => Promise<string>
  user?: {
    id: string
    displayName?: string
  }
  ui?: UIOptions
  systemPrompt?: string
  messages?: Message[]
  callbacks?: AgentCallbacks
  transport?: 'websocket' | 'sse'
  reconnect?: {
    maxRetries?: number
    delayMs?: number
  }
}

export interface WebSocketMessage {
  id: string
  type: string
  protocolVersion?: 1
  conversationId?: string
  requestId?: string
  sequence?: number
  timestamp: string
  payload: Record<string, unknown>
}

export interface OutgoingMessage {
  type: string
  payload: Record<string, unknown>
}
