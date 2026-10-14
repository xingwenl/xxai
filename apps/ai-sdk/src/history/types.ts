/**
 * 「会话历史记录」展示模块对宿主冻结的读侧契约。
 *
 * 本文件只描述**后端原生 payload 的形状**，不包含任何 HTTP 调用、后端路径或鉴权：
 * 数据由宿主实现 `ConversationHistorySource` 注入（见 ADR
 * `docs/adr/0003-conversation-history-read-boundary.md`）。字段名与后端接口
 * `GET /platforms/{platform_id}/conversations*` 及 embed 同形状投影逐字对齐。
 */
import type {
  AgentLoopRun,
  AgentLoopStep,
  AgentLoopStatus,
  AgentLoopStepStatus,
  MessageContentBlock
} from '../core'

/** 会话列表项（会话头 + 列表渲染所需的轻量统计，不含消息正文）。 */
export interface ConversationSummaryPayload {
  id: number
  platform_id: number
  agent_id: number
  agent_name: string | null
  principal_type: 'user' | 'end_user'
  principal_id: number
  principal_name: string | null
  title: string | null
  status: string
  message_count: number
  last_message_preview: string | null
  last_message_at: string | null
  created_at: string
}

/** 会话列表分页信封。 */
export interface ConversationPagePayload {
  items: ConversationSummaryPayload[]
  total: number
  page: number
  page_size: number
}

/**
 * Agent Loop 的单个步骤。
 *
 * 之所以不直接引用 `AgentLoopStep`，是因为后端只下发渲染所需的子集；
 * 字段类型与 `AgentLoopStep` 对应字段逐一对齐（`status` 用
 * `AgentLoopStepStatus`、`error` 用 `AgentLoopStep['error']`），
 * 从而保证 payload 可直接赋值给 `Message['loop']`。
 */
export interface ConversationLoopStepPayload {
  id: string
  sequence: number
  stepType: AgentLoopStep['stepType']
  title: AgentLoopStep['title']
  status: AgentLoopStepStatus
  outputSummary: AgentLoopStep['outputSummary']
  inputSummary: AgentLoopStep['inputSummary']
  thinkingText: AgentLoopStep['thinkingText']
  toolName: AgentLoopStep['toolName']
  skillName: AgentLoopStep['skillName']
  citationRefs: AgentLoopStep['citationRefs']
  error: AgentLoopStep['error']
}

/** Agent Loop 的一次运行（一个 assistant 消息最多一条）。 */
export interface ConversationLoopRunPayload {
  id: string
  requestId: AgentLoopRun['requestId']
  status: AgentLoopStatus
  summary: AgentLoopRun['summary']
  steps: ConversationLoopStepPayload[]
}

/** 单条会话消息；`loop` 与 `AgentLoopRun` 赋值兼容。 */
export interface ConversationMessagePayload {
  id: number
  conversation_id: number
  role: 'user' | 'assistant' | 'tool'
  content: string
  status: string
  /**
   * 结构化内容块。后端下发的是已通过 `sanitize_content_blocks` 清洗、
   * 与 SDK `MessageContentBlock` 同形状的 JSON，因此这里直接声明为该类型，
   * 让 `mapHistoryMessages` 无需强制转型即可消费。
   */
  content_blocks: MessageContentBlock[]
  citations: unknown[]
  knowledge_grounded: boolean
  tool_call_id: string | null
  created_at: string
  updated_at: string
  loop: ConversationLoopRunPayload | null
}

/** 会话列表查询参数（全部可选，缺省由宿主实现决定默认值）。 */
export interface ConversationListParams {
  page?: number
  page_size?: number
  agent_id?: number
  keyword?: string
  status?: string
  principal_type?: 'user' | 'end_user'
  principal_id?: number
}

/**
 * 宿主注入的数据源。SDK 只调用这两个方法，不知道它们背后是 HTTP、
 * IndexedDB 还是内存数组，也不参与鉴权与平台隔离。
 */
export interface ConversationHistorySource {
  listConversations(params: ConversationListParams): Promise<ConversationPagePayload>
  listMessages(conversationId: number | string): Promise<ConversationMessagePayload[]>
}
