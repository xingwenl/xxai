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
  asset_id?: string
  url?: string
  alt?: string
  fileName?: string
  mimeType?: string
  mime_type?: string
  size?: number
  componentName?: string
  component_name?: string
  props?: Record<string, unknown>
  fallback?: string
  metadata?: Record<string, unknown>
}

export interface KnowledgeBaseRef {
  id?: number | string
  name?: string
  slug?: string
}

export interface KnowledgeCitation {
  title: string
  sourceUrl?: string
  source?: string
  text?: string
  knowledgeBase?: KnowledgeBaseRef
  [key: string]: unknown
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
export type AgentLoopStepStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'waiting_confirmation' | 'waiting_question'

export interface AgentLoopStep {
  id: string
  sequence: number
  stepType: AgentLoopStepType | string
  title: string
  status: AgentLoopStepStatus
  inputSummary?: string
  outputSummary?: string
  thinkingText?: string
  toolName?: string
  skillName?: string
  skillVersion?: string
  citationRefs?: KnowledgeCitation[]
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
  timeline?: AssistantTimelineEntry[]
  loop?: AgentLoopRun
  timestamp: Date
  conversationId?: string
  requestId?: string
  metadata?: Record<string, unknown>
}

export type AssistantTimelineEntry =
  | { kind: 'text'; id: string; text: string }
  | { kind: 'step'; id: string; stepId: string }

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
  /**
   * 聊天 UI 挂载容器。传入时进入嵌入式模式：聊天窗口默认展开并填满该容器
   * （容器需有确定高度），不渲染悬浮按钮与拖拽/缩放手柄，`open/close/toggle`
   * 不再控制窗口开关；不传时保持悬浮窗行为。
   */
  container?: HTMLElement
  colors?: UIColors
  /**
   * 悬浮窗拖拽与缩放配置。默认宽高 430×680，最小 320×480，
   * 最大不超过视口减去四周留白；所有值均为 CSS 像素。嵌入式模式下不生效。
   */
  window?: UIWindowBounds
  /**
   * 布局形态。缺省 `single`：保持既有的单栏消息流（悬浮窗 / 嵌入式均同）。
   * `desktop`：PC 双栏，宽屏下左侧常驻会话列表、右侧对话区；窄于
   * 768px 时自动退化为单栏并用抽屉收纳会话列表。
   */
  layout?: 'single' | 'desktop'
  /** 双栏布局下左侧会话列表的配置；仅在 `layout: 'desktop'` 时生效。 */
  sidebar?: {
    /** 列表宽度（CSS 像素），默认 260，会被限制在 200–360 之间。 */
    width?: number
  }
}

export interface UIWindowBounds {
  width?: number
  height?: number
  minWidth?: number
  minHeight?: number
  maxWidth?: number
  maxHeight?: number
}

export interface UIColors {
  primary?: string
  primaryForeground?: string
  userMessageBackground?: string
  userMessageForeground?: string
  sendButtonBackground?: string
  sendButtonForeground?: string
}

/**
 * 会话列表项。后端只下发列表渲染所需的轻量元数据，消息正文仍由
 * `openConversation()` 拉取的快照提供。
 */
export interface ConversationSummary {
  id: number
  title?: string | null
  createdAt: string
  messageCount: number
  lastMessagePreview?: string | null
}

/** 会话列表分页结果。 */
export interface ConversationPage {
  items: ConversationSummary[]
  total: number
  page: number
  pageSize: number
}

export interface AgentCallbacks {
  onMessage?: (message: Message) => void
  onConnectionState?: (state: ConnectionState) => void
  onToolCall?: (name: string, input: unknown) => void
  onToolResult?: (name: string, result: unknown) => void
  onError?: (error: Error) => void
  onConfirmationRequired?: (confirmation: ToolConfirmation) => void
  onQuestionRequired?: (question: AgentQuestion) => void
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

export interface QuestionOption {
  id: string
  label: string
}

export interface AgentQuestion {
  questionId: string
  question: string
  description?: string
  options: QuestionOption[]
  allowFreeText: boolean
  requireSelection?: boolean
  expiresAt?: string
}

export interface QuestionAnswer {
  selectedOptionId?: string
  freeText?: string
}

/** embed client 基本信息，由网关在 session_ready 事件中下发。 */
export interface EmbedClientInfo {
  clientId?: string
  name?: string
  tokenTtlSeconds?: number
  maxTokensPerMinute?: number | null
  maxConnections?: number | null
}

/** agent 基本信息，由网关在 session_ready 事件中下发。 */
export interface AgentInfo {
  agentId?: number
  name?: string
  slug?: string
  description?: string | null
}

/** 单个配额资源当前时间窗口的限额与用量快照。 */
export interface QuotaResourceUsage {
  limit: number
  current: number
}

/** 当前时间窗口的配额快照（窗口是时间维度，非会话）。 */
export interface QuotaUsage {
  windowSeconds?: number
  resources?: {
    connection?: QuotaResourceUsage
    message?: QuotaResourceUsage
    model_tokens?: QuotaResourceUsage
    token_issue?: QuotaResourceUsage
  }
}

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
  /** HTTP API 根路径，用于上传、下载等非 WebSocket 调用。未提供时从 endpoint 推导。 */
  baseUrl?: string
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
  /** 本地消息和会话 ID 的存储键；未提供时按平台、Agent 和用户隔离。 */
  storageKey?: string
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

// ---------------------------------------------------------------------------
// 附件相关类型
// ---------------------------------------------------------------------------

/** 附件引用，在消息发送时携带。 */
export interface AttachmentRef {
  assetId: string
  filename: string
  mimeType: string
  size: number
  /** 当前页面即时预览地址，不会发送到后端协议。 */
  previewUrl?: string
}

/** 附件上传和处理的实时状态。 */
export type AttachmentUploadState =
  | 'pending'
  | 'uploading'
  | 'uploaded'
  | 'processing'
  | 'ready'
  | 'failed'
  | 'unsupported'

/** 输入框中待上传/已上传的附件条目。 */
export interface AttachmentEntry {
  id: string
  file: File
  assetId?: string
  filename: string
  mimeType: string
  size: number
  state: AttachmentUploadState
  progress?: number
  errorMessage?: string
  thumbnailUrl?: string
}

/** sendMessage 的扩展选项，保持向后兼容的 sendMessage(text) 签名。 */
export interface SendMessageOptions {
  attachments?: AttachmentRef[]
  systemPrompt?: string
}
