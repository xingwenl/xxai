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

export type ContentBlockStatus = 'pending' | 'streaming' | 'completed' | 'failed'

export interface MessageContentBlock {
  id: string
  type: 'text' | 'markdown' | 'image' | 'file' | 'table' | 'chart' | 'actions' | 'custom' | 'error' | string
  status?: ContentBlockStatus
  text?: string
  assetId?: string
  alt?: string
  fileName?: string
  mimeType?: string
  size?: number
  componentName?: string
  props?: Record<string, unknown>
  fallback?: string
  metadata?: Record<string, unknown>
}

export type AgentLoopStepType =
  | 'thinking'
  | 'knowledge_retrieval'
  | 'skill_instruction'
  | 'skill_tool'
  | 'builtin_tool'
  | 'host_tool'
  | 'mcp_tool'
  | 'model_generation'
  | 'handoff'
  | 'guardrail'

export type AgentLoopStatus = 'running' | 'completed' | 'failed' | 'cancelled' | 'waiting_confirmation'
export type AgentLoopStepStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'waiting_confirmation'

export interface AgentLoopStep {
  id: string
  sequence: number
  stepType: AgentLoopStepType | string
  title: string
  status: AgentLoopStepStatus
  outputSummary?: string
  toolName?: string
  skillName?: string
  skillVersion?: string
  citationRefs?: unknown[]
  error?: Record<string, unknown>
  startedAt?: string
  completedAt?: string
  durationMs?: number
}

export interface AgentLoopRun {
  id: string
  requestId: string
  status: AgentLoopStatus
  summary?: string
  steps: AgentLoopStep[]
}

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
  contentBlocks?: MessageContentBlock[]
  loop?: AgentLoopRun
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
  signal?: AbortSignal
}

export interface UIOptions {
  mode: 'headless' | 'floating' | 'embedded'
  position?: 'left' | 'right'
  locale?: string
  theme?: 'light' | 'dark' | 'auto'
  container?: HTMLElement
  colors?: UIColors
}

export interface UIColors {
  primary?: string
  primaryForeground?: string
  userMessageBackground?: string
  userMessageForeground?: string
  sendButtonBackground?: string
  sendButtonForeground?: string
}

export interface AgentCallbacks {
  onMessage?: (message: Message) => void
  onConnectionState?: (state: ConnectionState) => void
  onToolCall?: (name: string, input: unknown) => void
  onToolResult?: (name: string, result: unknown) => void
  onError?: (error: Error) => void
  onConfirmationRequired?: (confirmation: ToolConfirmation) => void
}

export type HostToolStatus =
  | 'requested'
  | 'awaiting_confirmation'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'rejected'
  | 'expired'

export type ToolType = 'mcp_tool' | 'host_tool'

export type ToolSideEffect = 'none' | 'navigation' | 'write' | 'financial' | 'external'

export interface ToolConfirmation {
  callId: string
  name: string
  toolType?: ToolType
  sideEffect?: ToolSideEffect
  summary?: Record<string, unknown>
  expiresAt?: string
}

/** @deprecated Use ToolConfirmation. Kept for SDK consumers on 0.1.x. */
export type HostToolConfirmation = ToolConfirmation

export interface TokenProviderContext {
  platformId: string
  agentId: string
  user?: {
    id: string
    displayName?: string
  }
}

export interface AgentClientOptions {
  endpoint: string
  platformId: string
  agentId: string
  getToken: (context: TokenProviderContext) => Promise<string>
  user?: {
    id: string
    displayName?: string
  }
  ui?: UIOptions
  systemPrompt?: string
  messages?: Message[]
  callbacks?: AgentCallbacks
  transport?: 'websocket'
  reconnect?: {
    maxRetries?: number
    delayMs?: number
  }
  pageTools?: {
    enabled?: boolean
    confirmationKeywords?: string[]
    maxCalls?: number
    maxDurationMs?: number
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
  requestId?: string
  payload: Record<string, unknown>
}

export interface HostToolCall {
  callId: string
  name: string
  arguments: unknown
  sideEffect: ToolDefinition['sideEffect']
  requiresConfirmation: boolean
}
