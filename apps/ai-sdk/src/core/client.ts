import type {
  SendMessageOptions,
  AgentCallbacks,
  AgentClientOptions,
  AgentInfo,
  ConnectionState,
  ContextCompacted,
  ContextCompactResult,
  ContextUsage,
  ConversationPage,
  EmbedClientInfo,
  AgentLoopRun,
  AgentLoopStep,
  AgentQuestion,
  AssistantTimelineEntry,
  Message,
  OutgoingMessage,
  QuestionAnswer,
  QuestionOption,
  QuotaUsage,
  ToolDefinition,
  ToolConfirmation,
  WebSocketMessage
} from './types'
import { agentError, agentErrorFromResponse, type AgentError } from './errors'
import { EventEmitter } from './event-emitter'
import { MessageStore } from './message-store'
import { ToolRegistry } from './tool-registry'
import { WebSocketTransport } from './websocket'
import type { Transport } from './transport'
import { createPageTools } from './page/tools'
import { mapHistoryMessages } from '../history/map-history'
import type { HistoryMessageLike } from '../history/map-history'

let messageId = 0
function generateId(): string {
  return `msg_${++messageId}_${Date.now()}`
}

function parseOptionalObject(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined
}

/** 只接受有限数值，其余（null/字符串/NaN/Infinity）一律当作缺失。 */
function finiteNumberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function finiteNumberOrZero(value: unknown): number {
  return finiteNumberOrNull(value) ?? 0
}

/**
 * 判定 token「即将过期」的提前量。
 *
 * 留出余量是为了覆盖两种情况：请求发出时 token 还有效、到达服务端时已过期；
 * 以及客户端与服务端之间的时钟偏差。
 */
const TOKEN_EXPIRY_MARGIN_MS = 30_000

/**
 * 从 JWT payload 里读出 `exp` 并换算成毫秒时间戳。
 *
 * 这里不验签——签名由服务端校验，客户端读 `exp` 只用于决定缓存的 token 是否
 * 还值得复用。非 JWT 或没有 `exp` 时返回 null，调用方据此退化为「不缓存」，
 * 与历史行为一致，把 token 生命周期交回宿主管理。
 */
function readTokenExpiryMs(token: string): number | null {
  const segment = token.split('.')[1]
  if (!segment) return null
  try {
    const base64 = segment.replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=')
    const payload = JSON.parse(atob(padded)) as { exp?: unknown }
    const exp = payload.exp
    return typeof exp === 'number' && Number.isFinite(exp) ? exp * 1000 : null
  } catch {
    return null
  }
}

/**
 * 把 `context_usage` 事件的 payload 归一成 `ContextUsage`。
 *
 * 网关允许 `windowTokens`/`percent`/`lastCompactedAt` 为 null，这里再做一次
 * 防御：字段缺失或类型不符时退回「窗口未知、无百分比」，调用方据此降级为
 * 只显示绝对 token 数，而不是渲染一个错误的占用环。
 */
function parseContextUsage(payload: Record<string, unknown>): ContextUsage {
  return {
    usedTokens: finiteNumberOrZero(payload.usedTokens),
    windowTokens: finiteNumberOrNull(payload.windowTokens),
    percent: finiteNumberOrNull(payload.percent),
    source: payload.source === 'estimated' ? 'estimated' : 'provider',
    lastCompactedAt: typeof payload.lastCompactedAt === 'string' ? payload.lastCompactedAt : null
  }
}

/** 把 `context_compacted` 事件的 payload 归一成 `ContextCompacted`。 */
function parseContextCompacted(payload: Record<string, unknown>): ContextCompacted {
  return {
    trigger: payload.trigger === 'manual' ? 'manual' : 'auto',
    ok: payload.ok !== false,
    reason: typeof payload.reason === 'string' ? payload.reason : null,
    tokensBefore: finiteNumberOrZero(payload.tokensBefore),
    tokensAfter: finiteNumberOrZero(payload.tokensAfter),
    windowTokens: finiteNumberOrNull(payload.windowTokens),
    percent: finiteNumberOrNull(payload.percent),
    summaryChars: finiteNumberOrZero(payload.summaryChars)
  }
}

export class AgentClient {
  private options: AgentClientOptions
  private transport: Transport
  /** 已由 compatibility_error 处理过的传输层错误，用于抑制紧随其后的重复 error。 */
  private _handledTransportError?: AgentError
  private eventEmitter: EventEmitter
  private messageStore: MessageStore
  private toolRegistry: ToolRegistry
  private _systemPrompt: string | undefined
  private _callbacks: AgentCallbacks = {}
  private conversationId: string | undefined
  private currentRequestId: string | undefined
  private activeRequestId: string | undefined
  private pendingAssistantMessage: { id: string; text: string; timeline?: AssistantTimelineEntry[]; loop?: AgentLoopRun } | null = null
  private pendingCitations: unknown[] = []
  private uiMounted = false
  private uiContainer: HTMLElement | null = null
  private pendingConfirmations = new Set<string>()
  private pendingQuestions = new Set<string>()
  private pendingHostCalls = new Map<string, { name: string; arguments: unknown }>()
  private pendingLoop: AgentLoopRun | null = null
  private _clientInfo: EmbedClientInfo | undefined
  private _agentInfo: AgentInfo | undefined
  private _quota: QuotaUsage | undefined
  /**
   * 当前会话的上下文占用快照。
   *
   * 与 `_quota`（时间窗口配额）不同：它属于单个会话，切会话时必须清空，
   * 否则新会话会显示上一个会话的占用。
   */
  private _contextUsage: ContextUsage | null = null
  /**
   * 缓存的 embed access token。
   *
   * 服务端签发的 token 是短期的（默认 10 分钟），远短于宿主登录态，因此不能
   * 像登录态那样一直复用：`_tokenExpiresAt` 记录它的过期时间点，`exp` 读不出来
   * 时置 0，表示「不可按时间判断，下次用到就重新换」。
   */
  private _token: string = ''
  private _tokenExpiresAt = 0
  /** 正在进行的换取请求；并发调用共用它，避免同一时刻打多次签发接口。 */
  private _tokenPromise: Promise<string> | null = null
  readonly storageKey: string

  /** 干净的 HTTP API 根路径，优先使用 baseUrl，否则从 WS endpoint 推导。 */
  private get _httpBaseUrl(): string {
    // baseUrl 已是完整的 HTTP API 根路径（含 /api/v1），直接使用，避免重复拼接前缀。
    if (this.options.baseUrl) return this.options.baseUrl.replace(/\/+$/, '')
    // 从 ws://host/api/v1/ws/agents/1 推导为 http://host/api/v1
    const ws = this.options.endpoint
    const http = ws.replace(/^ws(s?):\/\//, 'http$1://')
    // 去掉 /ws/agents/... 后缀，只保留 /api/v1 前缀
    return http.replace(/\/ws\/agents\/.*$/, '').replace(/\/+$/, '')
  }

  constructor(options: AgentClientOptions) {
    this.options = {
      ...options,
      ui: {
        mode: 'floating',
        position: 'right',
        theme: 'auto',
        locale: 'zh-CN',
        // 默认不渲染 Agent 过程卡片，只保留对话正文；显式传 true 才展示。
        showAgentSteps: false,
        ...options.ui
      },
      transport: options.transport || 'websocket',
      reconnect: {
        maxRetries: 5,
        delayMs: 3000,
        ...options.reconnect
      }
    }

    this._systemPrompt = options.systemPrompt
    this.storageKey = options.storageKey || `xxai-agent:${options.platformId}:${options.agentId}:${options.user?.id || 'anonymous'}`
    this.eventEmitter = new EventEmitter()
    const persisted = this.readPersistedState()
    this.conversationId = persisted?.conversationId
    this.messageStore = new MessageStore(persisted?.messages || options.messages || [])
    this.toolRegistry = new ToolRegistry()
    this._callbacks = options.callbacks || {}

    this.transport = new WebSocketTransport({
      endpoint: this.options.endpoint,
      // 传输层只关心「拿一枚当前可用的 token」；缓存与刷新策略统一在 _getToken 里。
      getToken: () => this._getToken(),
      platformId: this.options.platformId,
      agentId: this.options.agentId,
      user: this.options.user,
      reconnect: this.options.reconnect,
      conversationId: this.conversationId
    })

    if (options.pageTools?.enabled) {
      this.registerTools(createPageTools(options.pageTools))
    }

    this.setupTransportListeners()
    this.persistState()
  }
  /**
   * 取得一枚可用的 embed access token。
   *
   * 宿主提供的 `getToken` 每次都会换一枚短期 token，所以 SDK 只在确认它还
   * 新鲜时复用缓存：`exp` 缺失（非 JWT）按「不缓存」处理，避免像过去那样
   * 把 10 分钟的 token 当成登录态一直用到用户刷新页面。
   */
  async _getToken(forceRefresh = false): Promise<string> {
    if (!this.options?.getToken) return ''
    const freshEnough =
      this._token &&
      this._tokenExpiresAt > Date.now() + TOKEN_EXPIRY_MARGIN_MS
    if (!forceRefresh && freshEnough) return this._token
    if (forceRefresh) this._invalidateToken()
    if (!this._tokenPromise) {
      const pending = this._issueToken().finally(() => {
        // 只清理自己的句柄：并发刷新时后来者可能已经建了新的请求。
        if (this._tokenPromise === pending) this._tokenPromise = null
      })
      this._tokenPromise = pending
    }
    return this._tokenPromise
  }

  /** 真正向宿主换取 token，并记录它的过期时间。 */
  private async _issueToken(): Promise<string> {
    const provider = this.options?.getToken
    if (!provider) return ''
    const token = await provider({
      platformId: this.options.platformId,
      agentId: this.options.agentId,
      user: this.options.user
    })
    this._token = token
    this._tokenExpiresAt = readTokenExpiryMs(token) ?? 0
    return token
  }

  /** 作废缓存：token 被服务端拒绝时调用，下次取用时重新向宿主换取。 */
  private _invalidateToken(): void {
    this._token = ''
    this._tokenExpiresAt = 0
    this._tokenPromise = null
  }

  /**
   * 发起需要 embed token 的 REST 请求。
   *
   * token 可能在两次请求之间过期，或被服务端提前判定失效（撤销、时钟偏差），
   * 因此 401 时作废缓存并重换一次 token 重试一次；仍失败就把错误交给调用方。
   * 不做无限重试，避免宿主 `getToken` 本身出问题时打转。
   */
  private async _authorizedFetch(
    url: string,
    init: {
      method?: string
      headers?: Record<string, string>
      body?: BodyInit
    } = {}
  ): Promise<Response> {
    const send = (token: string) =>
      fetch(url, {
        ...init,
        headers: { ...init.headers, Authorization: `Bearer ${token}` }
      })
    const response = await send(await this._getToken())
    if (response.status !== 401) return response
    const refreshed = await this._getToken(true)
    return send(refreshed)
  }

  /** 获取受保护的会话资源，返回仅在当前页面有效的 Blob URL。 */
  async loadAsset(url: string): Promise<string> {
    const endpoint = this._httpBaseUrl
    const resourceUrl = new URL(url, endpoint).toString()
    const response = await this._authorizedFetch(resourceUrl)
    if (!response.ok) {
      throw await agentErrorFromResponse(response, 'asset request failed')
    }
    return URL.createObjectURL(await response.blob())
  }

  private setupTransportListeners(): void {
    if (this.transport instanceof WebSocketTransport) {
      // 兼容性失败在传输层是「先 compatibility_error、再 error」成对发出的。
      // 这里消费前者拿到结构化错误码，并把紧随其后的 error 标记为已处理，
      // 避免同一次失败让调用方收到两条错误。
      this.transport.on('compatibility_error', (error: AgentError) => {
        this._handledTransportError = error
        this.handleRequestError({
          code: error.code ?? 'agent_connection_failed',
          message: error.message,
          retryable: error.retryable === true,
          details: error.details
        })
      })
      this.transport.on('state', (state: ConnectionState) => {
        this.handleConnectionStateChange(state)
      })
    }

    this.transport.on('open', () => {
      console.log('Connection opened')
    })

    this.transport.on('message', (msg: WebSocketMessage) => {
      this.handleTransportMessage(msg)
    })

    this.transport.on('close', () => {
      console.log('Connection closed')
    })

    this.transport.on('error', (error: Error) => {
      console.error('Connection error:', error)
      if (error === this._handledTransportError) {
        this._handledTransportError = undefined
        return
      }
      this.handleRequestError({
        code: 'agent_connection_failed',
        message: 'Agent 连接失败，本轮对话已结束',
        retryable: true,
        details: { error: error.message }
      })
    })
  }

  private handleConnectionStateChange(state: ConnectionState): void {
    this._callbacks.onConnectionState?.(state)
    this.eventEmitter.emit('connection_state', state)
  }

  private handleTransportMessage(msg: WebSocketMessage): void {
    // 记录处理前的会话 ID：后端在首条消息时才创建会话，这个「从无到有」的
    // 变化是侧栏需要刷新列表的唯一信号。
    const previousConversationId = this.conversationId
    // 网关在每个会话事件的顶层返回 conversationId；同步到 Client，保证
    // UI 消息、宿主工具上下文和后续重连看到的是同一个会话标识。
    if (typeof msg.conversationId === 'string' && msg.conversationId) {
      console.info('[xxai-agent][conversation] client synchronized conversation id', {
        eventType: msg.type,
        requestId: msg.requestId,
        previousConversationId: this.conversationId,
        conversationId: msg.conversationId
      })
      this.conversationId = msg.conversationId
      if (this.transport instanceof WebSocketTransport) {
        this.transport.setConversationId(msg.conversationId)
      }
      this.persistState()
    }
    let message: Message | null = null

    switch (msg.type) {
      case 'session_ready':
        if (typeof msg.payload.sessionId === 'string' && msg.payload.sessionId) {
          this.conversationId = msg.payload.sessionId
          if (this.transport instanceof WebSocketTransport) {
            this.transport.setConversationId(msg.payload.sessionId)
          }
          this.persistState()
        }
        // 网关在认证成功后下发 embed client/agent 基本信息与配额快照；
        // 旧网关没有这些字段时保持 undefined，由 UI 回退到默认标题。
        this._clientInfo = parseOptionalObject(msg.payload.client) as
          | EmbedClientInfo
          | undefined
        this._agentInfo = parseOptionalObject(msg.payload.agent) as
          | AgentInfo
          | undefined
        this._quota = parseOptionalObject(msg.payload.quota) as QuotaUsage | undefined
        this.eventEmitter.emit('client_info', {
          client: this._clientInfo,
          agent: this._agentInfo,
          quota: this._quota
        })
        break
      case 'message_started':
        // 重连 replay 可能再次包含同一个请求的 message_started。此时不能
        // 清空已经在断线前累计的正文，否则恢复后消息列表只剩断线之后的 delta。
        const isSameRequest =
          Boolean(msg.requestId) && msg.requestId === this.currentRequestId
        this.currentRequestId = msg.requestId || this.currentRequestId
        this.activeRequestId = msg.requestId || this.activeRequestId
        if (!isSameRequest || !this.pendingAssistantMessage) {
          this.pendingAssistantMessage = {
            id: generateId(),
            text: '',
            timeline: [],
            loop: this.pendingLoop || undefined
          }
          this.pendingCitations = []
        }
        this.updatePendingMessage()
        break
      case 'agent_loop_started':
        this.pendingLoop = {
          id: String(msg.payload.loopRunId || msg.payload.id || msg.requestId || generateId()),
          requestId: String(msg.requestId || ''),
          status: 'running',
          summary: typeof msg.payload.summary === 'string' ? msg.payload.summary : undefined,
          steps: []
        }
        if (this.pendingAssistantMessage) this.pendingAssistantMessage.loop = this.pendingLoop
        this.eventEmitter.emit('agent_loop', this.pendingLoop)
        this.updatePendingMessage()
        break
      case 'agent_step_started':
      case 'agent_step_completed': {
        if (!this.pendingLoop) {
          this.pendingLoop = {
            id: String(msg.payload.loopRunId || msg.payload.id || msg.requestId || generateId()),
            requestId: String(msg.requestId || ''),
            status: 'running',
            steps: []
          }
        }
        const step = this.mergeLoopStep(msg)
        const index = this.pendingLoop.steps.findIndex((item) => item.id === step.id)
        if (index === -1) this.pendingLoop.steps.push(step)
        else this.pendingLoop.steps[index] = { ...this.pendingLoop.steps[index], ...step }
        this.upsertTimelineStep(step.id)
        this.eventEmitter.emit('agent_loop', { ...this.pendingLoop, steps: [...this.pendingLoop.steps] })
        this.pendingAssistantMessage && (this.pendingAssistantMessage.loop = this.pendingLoop)
        this.updatePendingMessage()
        break
      }
      case 'agent_step_delta': {
        if (!this.pendingLoop) break
        const payload = msg.payload as Record<string, unknown>
        const content = typeof payload.content === 'string' ? payload.content : ''
        if (payload.field !== 'thinking' || !content) break
        const stepId = typeof payload.stepId === 'string' ? payload.stepId : ''
        let index = this.pendingLoop.steps.findIndex((item) => item.id === stepId)
        if (index === -1) {
          index = this.pendingLoop.steps.findIndex(
            (item) => item.stepType === 'model_generation' || item.stepType === 'thinking'
          )
        }
        if (index === -1) break
        const step = this.pendingLoop.steps[index]
        this.pendingLoop.steps[index] = {
          ...step,
          thinkingText: (step.thinkingText || '') + content
        }
        this.eventEmitter.emit('agent_loop', { ...this.pendingLoop, steps: [...this.pendingLoop.steps] })
        this.pendingAssistantMessage && (this.pendingAssistantMessage.loop = this.pendingLoop)
        this.updatePendingMessage()
        break
      }
      case 'agent_loop_completed':
        if (this.pendingLoop) {
          this.pendingLoop = {
            ...this.pendingLoop,
            status: (msg.payload.status as AgentLoopRun['status']) || 'completed',
            summary: typeof msg.payload.summary === 'string' ? msg.payload.summary : this.pendingLoop.summary
          }
          this.eventEmitter.emit('agent_loop', this.pendingLoop)
          this.pendingAssistantMessage && (this.pendingAssistantMessage.loop = this.pendingLoop)
          this.updatePendingMessage()
        }
        break
      case 'message_delta':
        // 重连 replay 可能从 message_started 之后开始；此时页面内没有待处理
        // assistant，需要先创建一个恢复中的占位消息，后续 delta 才能正常合并。
        if (!this.pendingAssistantMessage) {
          this.currentRequestId = msg.requestId || this.currentRequestId
          this.pendingAssistantMessage = {
            id: generateId(),
            text: '',
            timeline: [],
            loop: this.pendingLoop || undefined
          }
        }
        if (this.pendingAssistantMessage) {
          const delta = (msg.payload.content as string) || ''
          this.pendingAssistantMessage.text += delta
          this.appendTimelineText(delta)
          this.updatePendingMessage()
        }
        break
      case 'citation':
        this.pendingCitations.push(msg.payload)
        this.eventEmitter.emit('citation', msg.payload)
        break
      case 'tool_call':
        this._callbacks.onToolCall?.(msg.payload.name as string, msg.payload.input)
        this.eventEmitter.emit('tool_call', msg.payload)
        break
      case 'tool_result':
        this._callbacks.onToolResult?.(msg.payload.name as string, msg.payload.result)
        this.eventEmitter.emit('tool_result', msg.payload)
        break
      case 'host_tool_call':
        void this.executeHostTool(msg)
        break
      case 'confirmation_required':
        this.pendingConfirmations.add(String(msg.payload.callId))
        const confirmation: ToolConfirmation = {
          callId: String(msg.payload.callId),
          name: String(msg.payload.name),
          toolType: msg.payload.toolType as ToolConfirmation['toolType'],
          sideEffect: msg.payload.sideEffect as ToolConfirmation['sideEffect'],
          summary: msg.payload.summary as Record<string, unknown> | undefined,
          expiresAt: typeof msg.payload.expiresAt === 'string' ? msg.payload.expiresAt : undefined
        }
        this._callbacks.onConfirmationRequired?.(confirmation)
        this.eventEmitter.emit('confirmation_required', confirmation)
        break
      case 'question_required':
        this.pendingQuestions.add(String(msg.payload.questionId))
        const question: AgentQuestion = {
          questionId: String(msg.payload.questionId),
          question: String(msg.payload.question || ''),
          description:
            typeof msg.payload.description === 'string'
              ? msg.payload.description
              : undefined,
          options: Array.isArray(msg.payload.options)
            ? (msg.payload.options as QuestionOption[])
            : [],
          allowFreeText: msg.payload.allowFreeText !== false,
          requireSelection:
            typeof msg.payload.requireSelection === 'boolean'
              ? msg.payload.requireSelection
              : true,
          expiresAt:
            typeof msg.payload.expiresAt === 'string'
              ? msg.payload.expiresAt
              : undefined,
        }
        this._callbacks.onQuestionRequired?.(question)
        this.eventEmitter.emit('question_required', question)
        break
      case 'message_completed':
        // 完整消息 replay 同样可能没有对应的 message_started。直接建立占位
        // 上下文，确保恢复后的回答进入 MessageStore 并触发 UI 更新。
        if (!this.pendingAssistantMessage) {
          this.currentRequestId = msg.requestId || this.currentRequestId
          this.pendingAssistantMessage = {
            id: generateId(),
            text: '',
            timeline: [],
            loop: this.pendingLoop || undefined
          }
        }
        if (this.pendingAssistantMessage) {
          const finalText = (msg.payload.content as string) || this.pendingAssistantMessage.text
          const completedLoop = msg.payload.loop as AgentLoopRun | undefined
          const loop = completedLoop && this.pendingLoop
            ? { ...this.pendingLoop, ...completedLoop, steps: completedLoop.steps?.length ? completedLoop.steps : this.pendingLoop.steps }
            : completedLoop || this.pendingLoop || undefined
          const timeline = this.pendingAssistantMessage.timeline?.length
            ? this.pendingAssistantMessage.timeline
            : finalText
              ? [{ kind: 'text' as const, id: `${this.pendingAssistantMessage.id}_text`, text: finalText }]
              : undefined
          message = {
            id: this.pendingAssistantMessage.id,
            role: 'assistant',
            type: 'text',
            content: {
              type: 'text',
              text: finalText
            },
            contentBlocks: Array.isArray(msg.payload.contentBlocks)
              ? msg.payload.contentBlocks as Message['contentBlocks']
              : [{ id: `${this.pendingAssistantMessage.id}_text`, type: 'markdown', text: finalText, status: 'completed' }],
            timeline,
            loop,
            timestamp: new Date(),
            conversationId: this.conversationId,
            requestId: this.currentRequestId,
            metadata: {
              citations: this.pendingCitations,
              knowledgeGrounded: msg.payload.knowledgeGrounded,
              ...(msg.payload.usage ? { usage: msg.payload.usage } : {})
            }
          }
          this.messageStore.addMessage(message)
          this.persistState()
          this.pendingAssistantMessage = null
          this.activeRequestId = undefined
          this.pendingCitations = []
          this.pendingLoop = null
        }
        break
      // 上下文占用：整体替换状态；窗口未知（null）时也照常下发，
      // 由调用方降级为只显示绝对 token 数。
      case 'context_usage': {
        const usage = parseContextUsage(msg.payload)
        this._contextUsage = usage
        this._callbacks.onContextUsage?.(usage)
        this.eventEmitter.emit('context_usage', usage)
        break
      }
      // 上下文压缩完成：压缩后模型只看到摘要，因此占用以 tokensAfter 为准。
      case 'context_compacted': {
        const result = parseContextCompacted(msg.payload)
        this._contextUsage = {
          usedTokens: result.tokensAfter,
          windowTokens: result.windowTokens ?? this._contextUsage?.windowTokens ?? null,
          percent: result.percent ?? this._contextUsage?.percent ?? null,
          source: this._contextUsage?.source ?? 'provider',
          lastCompactedAt: new Date().toISOString()
        }
        this._callbacks.onContextCompacted?.(result)
        this.eventEmitter.emit('context_usage', this._contextUsage)
        this.eventEmitter.emit('context_compacted', result)
        break
      }
      case 'error': {
        const payload = msg.payload as Record<string, unknown>
        // 网关单独回 embed_token 错误码时说明缓存 token 已被判失效（过期或撤销）。
        // 立刻作废缓存，后面的自动重连才会换到新 token，而不是拿旧 token 重试到
        // 重连次数耗尽、聊天彻底断死。
        if (payload.code === 'embed_token') this._invalidateToken()
        this.handleRequestError(payload, msg.requestId)
        break
      }
      default:
        console.log('Unhandled message type:', msg.type)
    }

    if (message) {
      this._callbacks.onMessage?.(message)
      this.eventEmitter.emit('message', message)
    }

    // 会话在首条消息时才由后端创建：此时必须通知侧栏把新会话拉进列表，
    // 否则用户发完消息仍看到「还没有历史会话」。
    if (!previousConversationId && this.conversationId) {
      this.eventEmitter.emit('conversations_changed', {
        reason: 'created',
        conversationId: this.conversationId
      })
    }
    // 回答完成或失败后消息数与末条摘要已经落库，刷新列表项内容。
    // 只在终态触发，避免每条流式 delta 都打一次列表接口；且要求确实存在
    // 会话，连接级错误（未建会话就失败）不需要刷新列表。
    if (
      this.conversationId &&
      (msg.type === 'message_completed' || msg.type === 'error')
    ) {
      this.eventEmitter.emit('conversations_changed', {
        reason: 'message',
        conversationId: this.conversationId
      })
    }
  }

  private updatePendingMessage(): void {
    if (this.pendingAssistantMessage) {
      // 这里可以触发 UI 更新
      this.eventEmitter.emit('message_updating', {
        id: this.pendingAssistantMessage.id,
        text: this.pendingAssistantMessage.text,
        timeline: this.pendingAssistantMessage.timeline,
        loop: this.pendingAssistantMessage.loop
      })
    }
  }

  private appendTimelineText(text: string): void {
    if (!this.pendingAssistantMessage || !text) return
    const timeline = this.pendingAssistantMessage.timeline || (this.pendingAssistantMessage.timeline = [])
    const last = timeline[timeline.length - 1]
    if (last && last.kind === 'text') {
      last.text += text
    } else {
      timeline.push({ kind: 'text', id: generateId(), text })
    }
  }

  private upsertTimelineStep(stepId: string): void {
    if (!this.pendingAssistantMessage || !stepId) return
    const timeline = this.pendingAssistantMessage.timeline || (this.pendingAssistantMessage.timeline = [])
    if (!timeline.some((entry) => entry.kind === 'step' && entry.stepId === stepId)) {
      timeline.push({ kind: 'step', id: generateId(), stepId })
    }
  }

  private handleRequestError(
    errorPayload: Record<string, unknown>,
    requestId?: string
  ): void {
    const normalized = agentError(errorPayload)
    const errorText = normalized.message
    const activeRequestId = requestId || this.currentRequestId || this.activeRequestId
    const failedLoop = this.pendingLoop
      ? {
          ...this.pendingLoop,
          status: 'failed' as const,
          summary: errorText,
          steps: this.pendingLoop.steps.map((step) =>
            step.status === 'running'
              ? { ...step, status: 'failed' as const, error: errorPayload }
              : step
          )
        }
      : undefined
    if (failedLoop) this.eventEmitter.emit('agent_loop', failedLoop)

    if (activeRequestId || this.pendingAssistantMessage) {
      const messageId = this.pendingAssistantMessage?.id || generateId()
      const failedMessage: Message = {
        id: messageId,
        role: 'assistant',
        type: 'error',
        content: { type: 'text', text: errorText },
        contentBlocks: [{
          id: `${messageId}_error`,
          type: 'error',
          text: errorText,
          status: 'failed',
          metadata: { error: errorPayload }
        }],
        loop: failedLoop,
        timestamp: new Date(),
        conversationId: this.conversationId,
        requestId: activeRequestId,
        metadata: { error: errorPayload }
      }
      this.messageStore.addMessage(failedMessage)
      this.persistState()
      this._callbacks.onMessage?.(failedMessage)
      this.eventEmitter.emit('message', failedMessage)
    }

    this.pendingAssistantMessage = null
    this.pendingLoop = null
    this.pendingCitations = []
    this.currentRequestId = undefined
    this.activeRequestId = undefined
    this._callbacks.onError?.(normalized)
    this.eventEmitter.emit('error', normalized)
  }

  private mergeLoopStep(msg: WebSocketMessage): AgentLoopStep {
    const payload = msg.payload
    return {
      id: String(payload.stepId || payload.id || generateId()),
      sequence: Number(payload.sequence || msg.sequence || 0),
      stepType: String(payload.stepType || 'thinking'),
      title: String(payload.title || '处理中'),
      status: (payload.status as AgentLoopStep['status']) || 'running',
      inputSummary: typeof payload.inputSummary === 'string' ? payload.inputSummary : undefined,
      outputSummary: typeof payload.outputSummary === 'string' ? payload.outputSummary : undefined,
      thinkingText: typeof payload.thinkingText === 'string' ? payload.thinkingText : undefined,
      toolName: typeof payload.toolName === 'string' ? payload.toolName : undefined,
      skillName: typeof payload.skillName === 'string' ? payload.skillName : undefined,
      skillVersion: typeof payload.skillVersion === 'string' ? payload.skillVersion : undefined,
      citationRefs: Array.isArray(payload.citationRefs) ? payload.citationRefs : undefined,
      error: payload.error && typeof payload.error === 'object' ? payload.error as Record<string, unknown> : undefined,
      durationMs: typeof payload.durationMs === 'number' ? payload.durationMs : undefined
    }
  }

  async connect(): Promise<void> {
    await this.transport.connect()
  }

  disconnect(): void {
    this.transport.disconnect()
    this.clearPendingConfirmations()
    this.clearPendingQuestions()
  }

  get connectionState(): ConnectionState {
    return this.transport.state
  }

  open(): void {
    this.eventEmitter.emit('ui_open')
  }

  close(): void {
    this.eventEmitter.emit('ui_close')
  }

  toggle(): void {
    this.eventEmitter.emit('ui_toggle')
  }

  destroy(): void {
    this.disconnect()
    this.eventEmitter.emit('ui_destroy')
    this.eventEmitter.removeAllListeners()
    this.messageStore.clearMessages()
    this.toolRegistry.clearCustomTools()
    this.clearPendingConfirmations()

    if (this.uiContainer && this.uiMounted) {
      this.uiContainer.remove()
      this.uiContainer = null
      this.uiMounted = false
    }
  }

  async sendMessage(text: string, options?: SendMessageOptions): Promise<void> {
    const attachments = options?.attachments || []
    const userMessage: Message = {
      id: generateId(),
      role: 'user',
      type: 'text',
      content: {
        type: 'text',
        text: text
      },
      contentBlocks: [
        {
          id: `${generateId()}_text`,
          type: 'markdown',
          text,
          status: 'completed'
        },
        ...attachments.map((attachment) => ({
          id: `attachment_${attachment.assetId}`,
          type: attachment.mimeType.startsWith('image/') ? 'image' as const : 'file' as const,
          assetId: attachment.assetId,
          asset_id: attachment.assetId,
          url: `/api/v1/assets/${attachment.assetId}`,
          previewUrl: attachment.previewUrl,
          alt: attachment.filename,
          fileName: attachment.filename,
          mimeType: attachment.mimeType,
          size: attachment.size,
          status: 'completed' as const
        }))
      ],
      timestamp: new Date(),
      conversationId: this.conversationId
    }

    this.messageStore.addMessage(userMessage)
    this.persistState()
    this._callbacks.onMessage?.(userMessage)
    this.eventEmitter.emit('message', userMessage)

    const payload: Record<string, unknown> = {
      text,
      ...(this._systemPrompt ? { systemPrompt: this._systemPrompt } : {}),
      // 显式下发解析后的布尔值：缺省为 false（不思考），避免"未传即沿用上游
      // 默认"导致思考被意外开启——DeepSeek 上游的默认是 enabled。
      thinking: this.options.thinking ?? false,
    }

    // 如果提供了附件，添加到 payload 中
    if (attachments.length > 0) {
      payload.attachments = attachments.map((att) => ({
        assetId: att.assetId,
        filename: att.filename,
        mimeType: att.mimeType,
        size: att.size,
      }))
    }

    if (options?.systemPrompt) {
      payload.systemPrompt = options.systemPrompt
    }

    const outgoing: OutgoingMessage = {
      type: 'message_send',
      requestId: generateId(),
      payload,
    }

    this.currentRequestId = outgoing.requestId
    this.activeRequestId = outgoing.requestId
    this.transport.send(outgoing)
  }

  /** 上传附件：已有会话时归入当前会话，否则由后端自动创建会话。 */
  async uploadAsset(
    file: File
  ): Promise<{ assetId: string; filename: string; mimeType: string; size: number; status: string; conversationId?: number }> {
    const baseUrl = this._httpBaseUrl

    const formData = new FormData()
    formData.append('file', file)
    const uploadUrl = this.conversationId
      ? `${baseUrl}/embed/conversations/${encodeURIComponent(this.conversationId)}/assets`
      : `${baseUrl}/embed/assets`

    const response = await this._authorizedFetch(uploadUrl, {
      method: 'POST',
      body: formData
    })

    if (!response.ok) {
      throw await agentErrorFromResponse(response, '上传失败')
    }

    const result = await response.json()
    const data = result.data

    // 首次上传时后端自动创建会话，同步 conversationId 回客户端
    if (data.conversationId && !this.conversationId) {
      this.conversationId = String(data.conversationId)
      if (this.transport instanceof WebSocketTransport) {
        this.transport.setConversationId(this.conversationId)
      }
      this.persistState()
    }

    return data
  }

  /** 查询附件处理状态和 chunks。 */
  async getAssetStatus(
    assetId: string
  ): Promise<{ assetId: string; status: string; chunks?: Array<{ position: number; content: string; pageNumber?: number; tokenCount: number }> }> {
    const baseUrl = this._httpBaseUrl

    const response = await this._authorizedFetch(
      `${baseUrl}/embed/conversations/${this.conversationId}/assets/${assetId}`
    )

    if (!response.ok) {
      throw await agentErrorFromResponse(response, '查询失败')
    }

    const result = await response.json()
    return result.data
  }

  /** 删除附件。 */
  async deleteAsset(assetId: string): Promise<void> {
    const baseUrl = this._httpBaseUrl

    const response = await this._authorizedFetch(
      `${baseUrl}/embed/conversations/${this.conversationId}/assets/${assetId}`,
      { method: 'DELETE' }
    )

    if (!response.ok) {
      throw await agentErrorFromResponse(response, '删除失败')
    }
  }

  cancelMessage(): void {
    if (!this.activeRequestId) return
    this.transport.send({
      type: 'message_cancel',
      requestId: this.activeRequestId,
      payload: {}
    })
    this.activeRequestId = undefined
    this.pendingAssistantMessage = null
    this.eventEmitter.emit('message_cancelled')
  }

  /** 当前绑定的会话 ID；新会话尚未落库时为 undefined。 */
  get currentConversationId(): string | undefined {
    return this.conversationId
  }

  /**
   * 拉取当前用户在指定 Agent 下的会话列表（按创建时间倒序）。
   *
   * 隔离条件由服务端从 embed token 读取，SDK 不传平台或用户参数。
   */
  async listConversations(options?: { page?: number; pageSize?: number }): Promise<ConversationPage> {
    const baseUrl = this._httpBaseUrl
    const params = new URLSearchParams({
      page: String(options?.page ?? 1),
      page_size: String(options?.pageSize ?? 20)
    })
    const response = await this._authorizedFetch(
      `${baseUrl}/embed/conversations?${params.toString()}`
    )
    if (!response.ok) {
      throw await agentErrorFromResponse(response, '会话列表加载失败')
    }
    const body = await response.json() as {
      data?: {
        items?: Array<{
          id: number
          title?: string | null
          created_at?: string
          message_count?: number
          last_message_preview?: string | null
        }>
        total?: number
        page?: number
        page_size?: number
      }
    }
    const data = body.data || {}
    return {
      items: (data.items || []).map((item) => ({
        id: item.id,
        title: item.title ?? null,
        createdAt: item.created_at || '',
        messageCount: item.message_count ?? 0,
        lastMessagePreview: item.last_message_preview ?? null
      })),
      total: data.total ?? 0,
      page: data.page ?? 1,
      pageSize: data.page_size ?? 20
    }
  }

  /**
   * 切换到指定会话：先重置本地流式/请求态，再拉取并渲染历史消息。
   *
   * 顺序很关键：任何残留的 pending 状态都会与历史消息叠加，表现出
   * 「历史 + 上一条流式回答」串台，因此重置必须先于渲染完成。
   */
  async openConversation(conversationId: number | string): Promise<Message[]> {
    const id = String(conversationId)
    // 切走前先放掉正在进行的请求，避免旧请求的事件落进新会话。
    this.cancelMessage()
    this._resetConversationState()
    this.conversationId = id
    if (this.transport instanceof WebSocketTransport) {
      // setConversationId 会同时把重放游标归零，防止新会话事件被去重丢弃。
      this.transport.setConversationId(id)
    }

    const messages = await this.fetchHistory(id)
    for (const message of messages) {
      this.messageStore.addMessage(message)
    }
    this.persistState()
    this.eventEmitter.emit('message', messages[messages.length - 1] as Message)
    this.eventEmitter.emit('history_loaded', { conversationId: id, messages })
    return this.getMessages()
  }

  /** 开新会话：解绑当前 conversationId，下一条消息由后端创建新会话。 */
  startNewConversation(): void {
    this.cancelMessage()
    this._resetConversationState()
    this.conversationId = undefined
    if (this.transport instanceof WebSocketTransport) {
      this.transport.setConversationId(undefined)
    }
    this.persistState()
    this.eventEmitter.emit('history_cleared')
    this.eventEmitter.emit('conversations_changed', { reason: 'created' })
  }

  /** 软删除会话：服务端只标记状态，消息与附件仍保留在库中。 */
  async deleteConversation(conversationId: number | string): Promise<void> {
    const id = String(conversationId)
    const baseUrl = this._httpBaseUrl
    const response = await this._authorizedFetch(
      `${baseUrl}/embed/conversations/${encodeURIComponent(id)}`,
      { method: 'DELETE' }
    )
    if (!response.ok) {
      throw await agentErrorFromResponse(response, '会话删除失败')
    }
    // 删掉的正是当前会话时，回到新建态，避免停在一个已删除的会话上。
    if (this.conversationId === id) {
      this.startNewConversation()
    }
    this.eventEmitter.emit('conversations_changed', { reason: 'deleted', conversationId: id })
  }

  /**
   * 请求服务端压缩当前会话的上下文。
   *
   * `instructions` 是可选附加聚焦点，会随请求发给后端用于生成摘要。返回压缩
   * 终态；后端对「没有可压缩内容」是幂等成功，此时 `compacted === false`、
   * `reason === 'nothing_to_compact'`，不算失败。当前没有会话（尚未创建或
   * 已切到新建态）时抛错，因为压缩必须绑定具体会话。
   */
  async compactContext(instructions?: string): Promise<ContextCompactResult | null> {
    const conversationId = this.conversationId
    if (!conversationId) {
      throw new Error('当前没有可压缩的会话：请先发送消息创建会话，或打开一个历史会话')
    }
    const baseUrl = this._httpBaseUrl
    const trimmed = typeof instructions === 'string' ? instructions.trim() : ''
    const response = await this._authorizedFetch(
      `${baseUrl}/embed/conversations/${encodeURIComponent(conversationId)}/context/compact`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(trimmed ? { instructions: trimmed } : {})
      }
    )
    if (!response.ok) {
      throw await agentErrorFromResponse(response, '上下文压缩失败')
    }
    const body = await response.json() as {
      data?: Record<string, unknown>
    }
    const data = body.data ?? {}
    const result: ContextCompactResult = {
      compacted: data.compacted === true,
      trigger: 'manual',
      ok: data.compacted === true,
      reason: typeof data.reason === 'string' ? data.reason : null,
      tokensBefore: finiteNumberOrZero(data.tokens_before),
      tokensAfter: finiteNumberOrZero(data.tokens_after),
      windowTokens: finiteNumberOrNull(data.window_tokens),
      percent: finiteNumberOrNull(data.percent),
      // REST 接口不返回摘要长度，按 0 处理，避免为它编造一个数字。
      summaryChars: 0
    }
    // 与服务端推送保持同一套状态更新语义：占用以压缩后的 token 数为准。
    this._contextUsage = {
      usedTokens: finiteNumberOrZero(data.used_tokens ?? data.tokens_after),
      windowTokens: result.windowTokens ?? this._contextUsage?.windowTokens ?? null,
      percent: result.percent ?? this._contextUsage?.percent ?? null,
      source: this._contextUsage?.source ?? 'provider',
      lastCompactedAt: new Date().toISOString()
    }
    // 回调（onContextCompacted）只对应服务端推送，这里只发事件，避免同一
    // 次手动压缩被通知两遍。
    this.eventEmitter.emit('context_usage', this._contextUsage)
    this.eventEmitter.emit('context_compacted', result)
    return result
  }

  /** 读取会话历史快照并转换成 SDK 的 Message 结构。 */
  private async fetchHistory(conversationId: string): Promise<Message[]> {
    const baseUrl = this._httpBaseUrl
    const response = await this._authorizedFetch(
      `${baseUrl}/embed/conversations/${encodeURIComponent(conversationId)}/messages`
    )
    if (!response.ok) {
      throw await agentErrorFromResponse(response, '历史消息加载失败')
    }
    const body = await response.json() as {
      data?: HistoryMessageLike[]
    }
    return mapHistoryMessages(body.data || [], conversationId)
  }

  /**
   * 重置跨会话复用的流式与请求状态。
   *
   * `MessageStore` 不在这里清空：调用方需要先拿到历史再决定何时替换，
   * 但所有「半成品」状态必须清掉，否则会与新会话内容串台。
   */
  private _resetConversationState(): void {
    this.messageStore.clearMessages()
    this.pendingAssistantMessage = null
    this.pendingLoop = null
    this.pendingCitations = []
    this.currentRequestId = undefined
    this.activeRequestId = undefined
    this.pendingConfirmations.clear()
    this.pendingQuestions.clear()
    // 占用是会话级状态：切走后必须清空，等新会话的首个 context_usage 到达。
    this._contextUsage = null
  }

  getMessages(): Message[] {
    return this.messageStore.getMessages()
  }

  addMessage(message: Message): void {
    this.messageStore.addMessage(message)
    this.persistState()
    this._callbacks.onMessage?.(message)
    this.eventEmitter.emit('message', message)
  }

  clearMessages(): void {
    this.messageStore.clearMessages()
    this.pendingAssistantMessage = null
  }

  clearLocalHistory(): void {
    this.cancelMessage()
    this.messageStore.clearMessages()
    this.pendingAssistantMessage = null
    this.pendingLoop = null
    this.pendingCitations = []
    this.conversationId = undefined
    this._contextUsage = null
    if (this.transport instanceof WebSocketTransport) this.transport.setConversationId(undefined)
    try {
      globalThis.localStorage?.removeItem(this.storageKey)
    } catch {
      // 浏览器禁用存储时保持内存状态可用。
    }
    this.eventEmitter.emit('history_cleared')
  }

  registerTool(tool: ToolDefinition): void {
    this.toolRegistry.registerTool(tool)
    if (this.transport instanceof WebSocketTransport) {
      const { execute: _execute, outputSchema: _outputSchema, timeoutMs: _timeoutMs, ...definition } = tool
      this.transport.registerHostTools({
        type: 'host_tools_register',
        payload: {
          tools: [definition]
        }
      })
    }
  }

  registerTools(tools: ToolDefinition[]): void {
    this.toolRegistry.registerTools(tools)
    if (this.transport instanceof WebSocketTransport) {
      this.transport.registerHostTools({
        type: 'host_tools_register',
        payload: {
          tools: tools.map(({ execute: _execute, outputSchema: _outputSchema, timeoutMs: _timeoutMs, sideEffect, ...baseDefinition }) => (
            { ...baseDefinition, ...(sideEffect ? { sideEffect } : {}) }
          )),
        }
      })
    }
  }

  unregisterTool(name: string): void {
    this.toolRegistry.unregisterTool(name)
  }

  getTool(name: string): ToolDefinition | undefined {
    return this.toolRegistry.getTool(name)
  }

  getToolNames(): string[] {
    return this.toolRegistry.getToolNames()
  }

  clearCustomTools(): void {
    this.toolRegistry.clearCustomTools()
  }

  resolveToolCall(callId: string, approved: boolean): void {
    if (!this.pendingConfirmations.has(callId)) return
    this.pendingConfirmations.delete(callId)
    const pending = this.pendingHostCalls.get(callId)
    if (this.transport instanceof WebSocketTransport) {
      this.transport.resolveToolCall(callId, approved)
    }
    if (approved && pending) void this.runHostTool(callId, pending.name, pending.arguments)
    if (!approved) this.pendingHostCalls.delete(callId)
    this.eventEmitter.emit('confirmation_resolved', { callId, approved })
  }

  answerQuestion(questionId: string, answer: QuestionAnswer): boolean {
    if (!this.pendingQuestions.has(questionId)) return false
    this.pendingQuestions.delete(questionId)
    if (this.transport instanceof WebSocketTransport) {
      this.transport.sendQuestionAnswer(questionId, answer)
    }
    this.eventEmitter.emit('question_resolved', { questionId, answer })
    return true
  }

  private clearPendingConfirmations(): void {
    for (const callId of this.pendingConfirmations) {
      this.eventEmitter.emit('confirmation_resolved', { callId, approved: false })
    }
    this.pendingConfirmations.clear()
    this.pendingHostCalls.clear()
  }

  private clearPendingQuestions(): void {
    for (const questionId of this.pendingQuestions) {
      this.eventEmitter.emit('question_resolved', { questionId })
    }
    this.pendingQuestions.clear()
  }

  private async executeHostTool(msg: WebSocketMessage): Promise<void> {
    const callId = String(msg.payload.callId || '')
    const name = String(msg.payload.name || '')
    // 关键排障日志：页面收到的宿主工具调用与本地注册清单必须同时可见，
    // 否则“注册成功但执行失败”只能靠服务端审计反推。
    console.info('[xxai-agent][host-tool] call received', {
      callId,
      name,
      requiresConfirmation: msg.payload.requiresConfirmation === true,
      registered: this.toolRegistry.getToolNames()
    })
    const tool = this.toolRegistry.getTool(name)
    if (!callId || !tool) {
      console.warn('[xxai-agent][host-tool] tool not registered', { callId, name })
      this.sendHostToolError(callId, 'host_tool_not_registered', 'Host tool is not registered')
      return
    }
    try {
      this.toolRegistry.validate(name, msg.payload.arguments)
      if (msg.payload.requiresConfirmation) {
        this.pendingConfirmations.add(callId)
        this.pendingHostCalls.set(callId, { name, arguments: msg.payload.arguments })
        const confirmation: ToolConfirmation = {
          callId,
          name,
          toolType: 'host_tool',
          sideEffect: msg.payload.sideEffect as ToolConfirmation['sideEffect'],
          summary: { arguments: msg.payload.arguments as unknown },
        }
        this._callbacks.onConfirmationRequired?.(confirmation)
        this.eventEmitter.emit('confirmation_required', confirmation)
        return
      }
      await this.runHostTool(callId, name, msg.payload.arguments)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Invalid arguments'
      console.warn('[xxai-agent][host-tool] invalid arguments', { callId, name, message })
      this.sendHostToolError(callId, 'host_tool_arguments_invalid', message)
    }
  }

  private async runHostTool(callId: string, name: string, params: unknown): Promise<void> {
    const tool = this.toolRegistry.getTool(name)
    if (!tool) {
      // 静默返回会让服务端一直等到工具超时（10 分钟）才判定失败，这里显式
      // 回报错误码，保证服务端日志与前端提示都能看到真实原因。
      console.warn('[xxai-agent][host-tool] tool disappeared before execution', { callId, name })
      this.sendHostToolError(callId, 'host_tool_not_registered', 'Host tool is not registered')
      return
    }
    const timeout = tool.timeoutMs ?? 10000
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeout)
    try {
      const result = await tool.execute(params, { conversationId: this.conversationId, requestId: callId, signal: controller.signal } as any)
      const encoded = JSON.stringify(result)
      if (encoded.length > 32 * 1024) throw new Error('host_tool_result_too_large')
      if (this.transport instanceof WebSocketTransport) this.transport.sendHostToolResult(callId, result)
      console.info('[xxai-agent][host-tool] result sent', { callId, name, bytes: encoded.length })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Tool execution failed'
      // 页面侧失败（page_unavailable / page_snapshot_stale / page_tool_budget_exceeded
      // / host_tool_result_too_large 等）只有这行日志能看到具体原因。
      console.warn('[xxai-agent][host-tool] execution failed', { callId, name, message })
      this.sendHostToolError(callId, 'host_tool_execution_failed', message)
    } finally {
      clearTimeout(timer)
      this.pendingHostCalls.delete(callId)
    }
  }

  private sendHostToolError(callId: string, code: string, message: string): void {
    if (this.transport instanceof WebSocketTransport) this.transport.sendHostToolError(callId, code, message)
  }

  setSystemPrompt(prompt: string): void {
    this._systemPrompt = prompt
  }

  private readPersistedState(): { messages: Message[]; conversationId?: string } | null {
    try {
      const raw = globalThis.localStorage?.getItem(this.storageKey)
      if (!raw) return null
      const value = JSON.parse(raw) as { version?: number; messages?: Message[]; conversationId?: string }
      if (value.version !== 1 || !Array.isArray(value.messages)) {
        globalThis.localStorage?.removeItem(this.storageKey)
        return null
      }
      const messages = value.messages.filter((message) => message && typeof message.id === 'string').map((message) => ({
        ...message,
        timestamp: new Date(message.timestamp)
      }))
      return { messages, conversationId: typeof value.conversationId === 'string' ? value.conversationId : undefined }
    } catch {
      try {
        globalThis.localStorage?.removeItem(this.storageKey)
      } catch {
        // 存储整体不可用时无需继续处理损坏缓存。
      }
      return null
    }
  }

  private persistState(): void {
    try {
      globalThis.localStorage?.setItem(this.storageKey, JSON.stringify({
        version: 1,
        conversationId: this.conversationId,
        messages: this.messageStore.getMessages()
      }))
    } catch {
      // 浏览器禁用或超出容量时降级为内存消息。
    }
  }

  getSystemPrompt(): string | undefined {
    return this._systemPrompt
  }

  /** embed client 基本信息（name/clientId/限额等）；旧网关未下发时为 undefined。 */
  get clientInfo(): EmbedClientInfo | undefined {
    return this._clientInfo
  }

  /** agent 基本信息（name/slug/description 等）；旧网关未下发时为 undefined。 */
  get agentInfo(): AgentInfo | undefined {
    return this._agentInfo
  }

  /** 当前时间窗口的配额快照；配额关闭或旧网关未下发时为 undefined。 */
  get quota(): QuotaUsage | undefined {
    return this._quota
  }

  /**
   * 当前会话的上下文占用快照；网关尚未推送或已切到新会话时为 null。
   *
   * 前端可直接读它渲染占用环，或订阅 `'context_usage'` 事件以获得变化通知。
   */
  get contextUsage(): ContextUsage | null {
    return this._contextUsage
  }

  get callbacks(): AgentCallbacks {
    return this._callbacks
  }

  set callbacks(callbacks: AgentCallbacks) {
    this._callbacks = callbacks
  }

  on(event: string, handler: (...args: any[]) => void): void {
    this.eventEmitter.on(event, handler)
  }

  off(event: string, handler: (...args: any[]) => void): void {
    this.eventEmitter.off(event, handler)
  }

  // UI 相关方法，供 UI 层调用
  _setUIMounted(mounted: boolean): void {
    this.uiMounted = mounted
  }

  _setUIContainer(container: HTMLElement | null): void {
    this.uiContainer = container
  }

  _getEventEmitter(): EventEmitter {
    return this.eventEmitter
  }

  _getMessageStore(): MessageStore {
    return this.messageStore
  }
}
