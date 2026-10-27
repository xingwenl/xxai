import type { AgentError } from './errors'

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

/**
 * 父运行派生的子运行摘要（运行期动态委派）。
 *
 * 只读投影：每个子运行有独立的会话与运行记录，这里只带渲染所需的终态信息，
 * 不含子运行自己的步骤明细，也不参与实时进度（子运行过程事件不回父会话）。
 */
export interface DelegatedRun {
  /** 子运行 ID（后端 `agent_loop_runs.id` 字符串化）。 */
  id: string
  agentSlug: string
  agentName: string
  /** 与 `AgentLoopStatus` 同源；后端新增状态时按原样透传。 */
  status: AgentLoopStatus | string
  summary: string | null
  conversationId: string | null
  /** 该子运行自己的 token 合计（父子不合并）；未记账时省略。 */
  usage?: DelegatedRunUsage
  /** `self`=自克隆父智能体，`bound`=派给后台绑定的子智能体；历史运行省略。 */
  mode?: 'self' | 'bound' | string
}

/** 单次子运行的 token 用量；与后端 `delegatedRuns[].usage` 逐字段一致。 */
export interface DelegatedRunUsage {
  promptTokens: number
  completionTokens: number
  totalTokens: number
}

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
  /** 本步骤（一次委派工具调用）扇出的子运行 ID；无子运行时省略或为空数组。 */
  delegatedRunIds?: string[]
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
  /** 本次运行派生的子运行摘要；无子运行时省略或为空数组。 */
  delegatedRuns?: DelegatedRun[]
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
  /**
   * 工具组名：后端按组按需加载工具时用它把工具分批绑定。
   * 不填时后端按工具名前缀回落（未登记前缀统一归 host 组并始终加载）。
   */
  group?: string
  timeoutMs?: number
  execute: (params: unknown, context: ToolContext) => Promise<unknown>
}

/** 工具组声明：只影响一次请求里怎么分批绑定工具，不参与授权与 schema 校验。 */
export interface ToolGroupDeclaration {
  /** 组名，与 ToolDefinition.group 对应 */
  name: string
  /** 中文标题，用于系统提示词里的工具目录 */
  title?: string
  /** 一句话说明，告诉模型这组里有什么能力 */
  description?: string
  /**
   * 是否立即加载（每轮都绑定）。默认 false：异步加载，等模型调用
   * load_tool_group 或入口预取命中后才绑定。
   */
  eager?: boolean
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
   * 布局形态，悬浮与嵌入式两种模式都支持。缺省 `single`：保持既有的
   * 单栏消息流。`desktop`：PC 双栏，左侧常驻会话列表、右侧对话区；
   * 当**聊天面板自身宽度**窄于 768px 时自动退化为单栏并用抽屉收纳列表
   * （悬浮窗默认宽 430px，因此默认走抽屉形态，把窗口拉宽后才常驻）。
   */
  layout?: 'single' | 'desktop'
  /** 双栏布局下左侧会话列表的配置；仅在 `layout: 'desktop'` 时生效。 */
  sidebar?: {
    /** 列表宽度（CSS 像素），默认 260，会被限制在 200–360 之间。 */
    width?: number
  }
  /**
   * 是否渲染 Agent 过程卡片（思考、工具调用、技能、知识库引用）。
   *
   * 缺省为 `false`：只保留对话正文。传 `true` 才展示过程明细。
   * 该开关只影响渲染，不改变后端是否产生过程事件。
   */
  showAgentSteps?: boolean
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
  onError?: (error: AgentError) => void
  onConfirmationRequired?: (confirmation: ToolConfirmation) => void
  onQuestionRequired?: (question: AgentQuestion) => void
  /**
   * 上下文占用变化（每轮模型调用后由网关推送一次）。
   *
   * 与 `agent.on('context_usage', handler)` 收到同一份数据，两种消费方式
   * 任选其一即可，同时订阅会各收到一次。
   */
  onContextUsage?: (usage: ContextUsage) => void
  /**
   * 上下文压缩完成（自动或手动）。
   *
   * 与 `agent.on('context_compacted', handler)` 等价；只表示收到了服务端
   * 推送的压缩结果，`ok === false` 时 `reason` 说明失败原因。
   */
  onContextCompacted?: (result: ContextCompacted) => void
  /**
   * 切换智能体成功。
   *
   * 与 `agent.on('agent_switched', handler)` 等价；此时 transport 已指向新
   * agent，`agent.getMessages()` 是该 agent 上次会话恢复后的消息。
   */
  onAgentSwitched?: (event: AgentSwitchedEvent) => void
  /**
   * 切换智能体失败（未绑定/无权限/忙碌/网络等）。
   *
   * 失败时原 agent 的连接与消息保持不变，UI 只需回退选择器与轻提示。
   */
  onAgentSwitchFailed?: (event: AgentSwitchFailedEvent) => void
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
  /**
   * 后台 embed client 是否允许终端用户切换智能体。
   *
   * 这是平台策略，由 `session_ready` 快照下发；SDK 必须同时拿到 `true` 和
   * 宿主传入的候选列表才展示切换入口。旧网关未下发时按 `false` 处理。
   */
  allowAgentSwitching?: boolean
}

/** agent 基本信息，由网关在 session_ready 事件中下发。 */
export interface AgentInfo {
  agentId?: number
  name?: string
  slug?: string
  description?: string | null
}

/**
 * 宿主传给 SDK 的候选智能体。
 *
 * SDK 不自行拉取列表：embed 接入是「平台管理员配置 client → 第三方宿主页面
 * 嵌入」，只有宿主知道要暴露哪些 agent 给终端用户；越权由换 token 时服务端的
 * 绑定校验兜底。
 */
export interface AgentSwitchOption {
  /** 与后台 Agent id 一致，同时用于换 token 与 WS 路径。 */
  agentId: number | string
  name: string
  slug?: string
  description?: string | null
}

/** 智能体切换的接入配置（能力开关本身仍以后台 embed client 策略为准）。 */
export interface AgentSwitchingOptions {
  /**
   * 候选智能体。为空或缺省时不渲染切换入口；宿主应只传「后台已启用且当前
   * client 已绑定」的 agent，避免展示必然失败的选项。
   */
  agents?: AgentSwitchOption[]
  /**
   * 本地强制隐藏入口（默认 `true`）。只能收窄、不能绕过后台开关：
   * 后台关闭时即使传 `true` 也不会启用。
   */
  enabled?: boolean
}

/** 切换成功后的快照，供 UI 刷新标题/头像与会话列表。 */
export interface AgentSwitchedEvent {
  /** 切换后的 agent id（字符串，与 token/WS 路径一致）。 */
  agentId: string
  /** 切换前的 agent id。 */
  previousAgentId: string
  /** 新 agent 的基本信息；连接完成后由 `session_ready` 补充。 */
  agent?: AgentInfo | null
  /** 恢复到的本地会话 id；没有历史时为 null。 */
  conversationId?: string | null
  /** 是否从本地存储恢复了该 agent 上次的会话。 */
  restored: boolean
}

/** 切换失败的分类，供宿主区分「未绑定/无权限」与「网络/配额」。 */
export type AgentSwitchFailureReason =
  | 'not_allowed'
  | 'not_supported'
  | 'busy'
  | 'not_bound'
  | 'quota'
  | 'network'
  | 'connection_failed'

/** 切换失败事件；失败时原 agent 的连接、消息与 token 缓存保持不变。 */
export interface AgentSwitchFailedEvent {
  /** 本次想切到的目标 agent id。 */
  agentId: string
  /** 当前仍是其连接与消息所属的原 agent id。 */
  previousAgentId: string
  reason: AgentSwitchFailureReason
  error?: AgentError
  /** 面向终端的中文文案，UI 可直接展示。 */
  message: string
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

/**
 * 当前会话的上下文占用快照。
 *
 * 由网关在每轮模型调用后通过 `context_usage` 事件下发；`windowTokens`
 * 为 null 表示后端拿不到模型窗口大小（例如 `source` 为 `estimated`），
 * 此时调用方只能展示绝对 token 数，无法给出百分比与占用环。
 */
export interface ContextUsage {
  usedTokens: number
  windowTokens: number | null
  /** 0–100 的百分比数值；窗口未知时为 null。 */
  percent: number | null
  source: 'provider' | 'estimated'
  lastCompactedAt: string | null
}

/**
 * 一次上下文压缩的终态结果（自动或手动）。
 *
 * `ok === false` 时 `reason` 形如 `summary_failed` / `summary_truncated`，
 * 且 `tokensAfter` 等于 `tokensBefore`（压缩未生效）。
 */
export interface ContextCompacted {
  trigger: 'auto' | 'manual'
  ok: boolean
  reason: string | null
  tokensBefore: number
  tokensAfter: number
  windowTokens: number | null
  percent: number | null
  summaryChars: number
}

/**
 * `compactContext()` 的返回值：压缩结果 + 本次是否真的发生了压缩。
 *
 * REST 接口对「没有可压缩内容」是幂等成功（HTTP 200 + `compacted: false` +
 * `reason: 'nothing_to_compact'`），因此单独带出 `compacted`，避免调用方把
 * 一次空操作误判成失败。
 */
export interface ContextCompactResult extends ContextCompacted {
  compacted: boolean
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
  /**
   * 请求级思考开关：`true` 进入思考模式，`false` 关闭。
   *
   * 缺省为 `false`（不思考）。该值随每次 `message_send` 下发，由后端翻译为
   * 上游厂商参数（DeepSeek 下发顶层 `thinking.type`）；因此同一 Agent 的不同
   * 请求可以各自决定是否思考。
   */
  thinking?: boolean
  messages?: Message[]
  /** 本地消息和会话 ID 的存储键；未提供时按平台、Agent 和用户隔离。 */
  storageKey?: string
  /**
   * 智能体切换的候选列表与本地开关。
   *
   * 是否真正允许切换仍以后台 embed client 的 `allowAgentSwitching` 为准；
   * 本选项只提供候选与「本地隐藏」能力，不能把后台关闭的能力打开。
   */
  agentSwitching?: AgentSwitchingOptions
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
