<template>
  <div class="xxai-reset" ref="rootRef">
    <FloatingButton v-if="!embedded && !isOpen" :position="position" @click="open" />
    <div
      v-if="isOpen"
      ref="panelRef"
      class="xxai-chat-window"
      :class="{
        dark: theme === 'dark',
        'xxai-chat-window--embedded': embedded,
        'xxai-chat-window--desktop': isDesktop,
        'xxai-chat-window--drawer-open': isDesktop && isNarrow && sidebarOpen
      }"
      :style="windowStyle"
    >
      <ConversationSidebar
        v-if="isDesktop && (!isNarrow || sidebarOpen)"
        :conversations="conversations"
        :active-id="activeConversationId"
        :loading="conversationsLoading"
        :error="conversationsError"
        :sidebar-width="sidebarWidth"
        @select="handleSelectConversation"
        @create="handleCreateConversation"
        @delete="handleDeleteConversation"
        @retry="loadConversations"
      />
      <!-- 窄屏抽屉展开时的遮罩：点击关闭列表，避免遮挡对话区。 -->
      <div
        v-if="isDesktop && isNarrow && sidebarOpen"
        class="xxai-sidebar-backdrop"
        aria-hidden="true"
        @click="sidebarOpen = false"
      />
      <div class="xxai-chat-main">
      <div
        class="xxai-chat-header"
        :class="{ 'xxai-chat-window-drag': !embedded }"
        @pointerdown="startDrag"
      >
        <button
          v-if="isDesktop && isNarrow"
          class="xxai-header-icon-btn"
          type="button"
          aria-label="会话列表"
          @click="sidebarOpen = !sidebarOpen"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <!-- <button v-if="!embedded" class="xxai-header-icon-btn" type="button" aria-label="返回" @click="close">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="m15 18-6-6 6-6" />
          </svg>
        </button> -->
        <div class="xxai-header-center">
          <div class="xxai-agent-avatar" aria-hidden="true">✦</div>
          <div class="xxai-header-info">
            <div class="xxai-header-name">{{ headerName }}</div>
            <div class="xxai-header-status">
              <span class="xxai-status-dot"></span>
              <span>{{ statusText }}</span>
            </div>
          </div>
        </div>
        <!-- <QuotaRing
          class="xxai-header-quota"
          :current="messageQuota?.current"
          :limit="messageQuota?.limit"
          :window-seconds="agent.quota?.windowSeconds"
        /> -->
        <button
          class="xxai-header-icon-btn xxai-header-clear-btn"
          type="button"
          :aria-label="confirmClear ? '确认清除聊天记录' : '清除聊天记录'"
          @click="onClearClick"
        >
          <span v-if="confirmClear" class="xxai-clear-confirm">确认？</span>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6h14ZM10 11v6M14 11v6" />
          </svg>
        </button>
        <button v-if="!embedded" class="xxai-header-icon-btn" type="button" aria-label="关闭" @click="close">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>
      <ChatMessageList
        :messages="messages"
        :pending-message="pendingMessage"
        :agent-name="agentName"
        :agent-description="agentDescription"
        :agent="agent"
        @button-click="handleButtonClick"
      />
      <ToolConfirmation
        v-if="pendingConfirmation && !hasCustomConfirmationHandler"
        :key="pendingConfirmation.callId"
        :agent="agent"
        :confirmation="pendingConfirmation"
      />
      <QuestionCard
        v-if="pendingQuestion && !hasCustomQuestionHandler"
        :key="pendingQuestion.questionId"
        :agent="agent"
        :question="pendingQuestion"
      />
      <ChatInput ref="chatInputRef" :is-sending="isSending" @send="handleSend" @stop="handleStop" @upload-attachment="handleUploadAttachment" />
      <div
        v-if="!embedded"
        class="xxai-window-resize-handle"
        aria-hidden="true"
        @pointerdown="startResize"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15v6h-6M21 3l-9 9M15 21l6-6" />
        </svg>
      </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, type Component } from 'vue'
import FloatingButton from './FloatingButton.vue'
import ChatMessageList from './ChatMessageList.vue'
import ChatInput from './ChatInput.vue'
import ToolConfirmation from './ToolConfirmation.vue'
import QuestionCard from './QuestionCard.vue'
import QuotaRing from './QuotaRing.vue'
import ConversationSidebar from './ConversationSidebar.vue'
import type {
  AgentClient,
  AgentQuestion,
  AssistantTimelineEntry,
  ConnectionState,
  ConversationSummary,
  UIOptions,
  Message,
  UIColors,
  UIWindowBounds,
  ToolConfirmation as ToolConfirmationData
} from '../../core'
import {
  clampWindowRect,
  defaultWindowRect,
  dragWindowRect,
  resizeWindowRect,
  resolveWindowBounds,
  type WindowRect,
} from '../window-layout'
import { resolveHeaderName } from '../header-name'
import { parseWindowRect, serializeWindowRect } from '../window-storage'

interface Props {
  agent: AgentClient
  position?: UIOptions['position']
  theme?: UIOptions['theme']
  title?: string
  colors?: UIColors
  window?: UIWindowBounds
  /**
   * 嵌入式模式：聊天窗口默认展开并填满容器，不渲染悬浮按钮、拖拽与缩放交互。
   */
  embedded?: boolean
  /** 布局形态；`desktop` 为 PC 双栏（左会话列表 + 右对话区）。 */
  layout?: UIOptions['layout']
  /** 双栏布局下左侧列表宽度（CSS 像素）。 */
  sidebarWidth?: number
}

const props = withDefaults(defineProps<Props>(), {
  position: 'right',
  theme: 'auto',
  title: 'AI Assistant',
  embedded: false,
  layout: 'single',
  sidebarWidth: 260
})

const isOpen = ref(false)
const isSending = ref(false)
const messages = ref<Message[]>([])
const conversations = ref<ConversationSummary[]>([])
const conversationsLoading = ref(false)
const conversationsError = ref('')
const sidebarOpen = ref(false)
const activeConversationId = ref<string | undefined>(undefined)
const pendingMessage = ref<{ id: string; text: string; timeline?: AssistantTimelineEntry[]; loop?: import('../../core').AgentLoopRun } | null>(null)
const pendingLoop = ref<import('../../core').AgentLoopRun | null>(null)
const connectionState = ref<ConnectionState>('disconnected')
const customComponents = ref<Record<string, Component>>({})
const pendingConfirmation = ref<ToolConfirmationData | null>(null)
const chatInputRef = ref<any>(null)
const pendingQuestion = ref<AgentQuestion | null>(null)
const viewport = ref({ width: 0, height: 0 })
// 聊天面板自身的渲染宽度，只服务双栏断点；与 `viewport` 严格分开，
// 否则会污染窗口缩放的上限计算（见 measurePanelWidth 注释）。
const panelWidth = ref(0)
const windowRect = ref<WindowRect>({ x: 0, y: 0, width: 430, height: 680 })
const confirmClear = ref(false)
const rootRef = ref<HTMLElement | null>(null)
/** 聊天面板本身：双栏断点按它的宽度判断，而非浏览器视口。 */
const panelRef = ref<HTMLElement | null>(null)
let clearTimer: ReturnType<typeof setTimeout> | null = null
let resizeObserver: ResizeObserver | null = null

const agent = props.agent
const hasCustomConfirmationHandler = computed(() => Boolean(agent.callbacks.onConfirmationRequired))
const hasCustomQuestionHandler = computed(() => Boolean(agent.callbacks.onQuestionRequired))
const colorStyle = computed(() => ({
  '--xxai-primary': props.colors?.primary || '#0EA5E9',
  '--xxai-primary-foreground': props.colors?.primaryForeground || '#FFFFFF',
  '--xxai-user-message-background': props.colors?.userMessageBackground || props.colors?.primary || '#0EA5E9',
  '--xxai-user-message-foreground': props.colors?.userMessageForeground || '#FFFFFF',
  '--xxai-send-background': props.colors?.sendButtonBackground || props.colors?.primary || '#0EA5E9',
  '--xxai-send-foreground': props.colors?.sendButtonForeground || props.colors?.primaryForeground || '#FFFFFF'
}))
const layoutContext = computed(() => ({
  viewportWidth: viewport.value.width,
  viewportHeight: viewport.value.height,
  position: props.position,
  bounds: resolveWindowBounds(props.window, viewport.value.width, viewport.value.height),
}))
const windowStyle = computed(() => ({
  ...(props.embedded
    ? colorStyle.value
    : {
        ...colorStyle.value,
        left: `${windowRect.value.x}px`,
        top: `${windowRect.value.y}px`,
        width: `${windowRect.value.width}px`,
        height: `${windowRect.value.height}px`,
      }),
}))
const windowStorageKey = computed(() => `${agent.storageKey}:window`)

// PC 双栏只在显式要求 desktop 布局时启用；缺省保持既有单栏行为。
const isDesktop = computed(() => props.layout === 'desktop')
// 窄屏（<768px）退化为单栏，会话列表改为抽屉收纳，避免挤压对话区。
// 断点看「面板自身宽度」而非视口：430px 悬浮窗停在宽视口上时也必须降级。
// 面板宽度未测量到（初始挂载前）时退回视口宽度，避免误判。
const isNarrow = computed(() => {
  const width = panelWidth.value || viewport.value.width
  return width > 0 && width < 768
})
// 列表宽度限制在可读区间，防止接入方传入过窄或过宽的值破坏布局。
const sidebarWidth = computed(() => Math.min(Math.max(props.sidebarWidth, 200), 360))

const statusText = computed(() => {
  const stateMap: Record<ConnectionState, string> = {
    disconnected: '未连接',
    connecting: '连接中...',
    connected: '已连接',
    reconnecting: '重连中...',
    error: '连接错误'
  }
  return stateMap[connectionState.value]
})
const headerName = computed(() => resolveHeaderName(agent.clientInfo?.name, props.title))
const messageQuota = computed(() => agent.quota?.resources?.message)
const agentName = computed(() => agent.agentInfo?.name || props.title)
const agentDescription = computed(() => agent.agentInfo?.description || undefined)

/**
 * 面板挂载后测量宽度并建立观察器。
 *
 * 悬浮窗在用户点击悬浮按钮之后才挂载、且拖拽缩放会改变宽度，因此不能只在
 * onMounted 里接一次：每次面板出现都要重新测量并 attach。
 */
function attachPanelObserver() {
  void nextTick(() => {
    measurePanelWidth()
    if (typeof ResizeObserver === 'undefined' || !panelRef.value) return
    resizeObserver?.disconnect()
    resizeObserver = new ResizeObserver(() => measurePanelWidth())
    resizeObserver.observe(panelRef.value)
  })
}

function open() {
  if (props.embedded) return
  isOpen.value = true
  attachPanelObserver()
}

function close() {
  if (props.embedded) return
  isOpen.value = false
}

function onClearClick() {
  if (!confirmClear.value) {
    confirmClear.value = true
    if (clearTimer) clearTimeout(clearTimer)
    clearTimer = setTimeout(() => {
      confirmClear.value = false
    }, 3000)
    return
  }
  if (clearTimer) clearTimeout(clearTimer)
  clearTimer = null
  confirmClear.value = false
  agent.clearLocalHistory()
}

let dragState: { startX: number; startY: number; rect: WindowRect } | null = null

function startDrag(event: PointerEvent) {
  if (props.embedded) return
  if (event.button !== 0) return
  if ((event.target as HTMLElement).closest('button')) return
  dragState = { startX: event.clientX, startY: event.clientY, rect: windowRect.value }
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', onDragEnd)
  window.addEventListener('pointercancel', onDragEnd)
  event.preventDefault()
}

function onDragMove(event: PointerEvent) {
  if (!dragState) return
  windowRect.value = dragWindowRect(
    dragState.rect,
    event.clientX - dragState.startX,
    event.clientY - dragState.startY,
    layoutContext.value,
  )
}

function onDragEnd() {
  dragState = null
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', onDragEnd)
  window.removeEventListener('pointercancel', onDragEnd)
  persistWindowRect()
}

let resizeState: { startX: number; startY: number; rect: WindowRect } | null = null

function startResize(event: PointerEvent) {
  if (event.button !== 0) return
  resizeState = { startX: event.clientX, startY: event.clientY, rect: windowRect.value }
  window.addEventListener('pointermove', onResizeMove)
  window.addEventListener('pointerup', onResizeEnd)
  window.addEventListener('pointercancel', onResizeEnd)
  event.preventDefault()
}

function onResizeMove(event: PointerEvent) {
  if (!resizeState) return
  windowRect.value = resizeWindowRect(
    resizeState.rect,
    event.clientX - resizeState.startX,
    event.clientY - resizeState.startY,
    layoutContext.value,
  )
}

function onResizeEnd() {
  resizeState = null
  window.removeEventListener('pointermove', onResizeMove)
  window.removeEventListener('pointerup', onResizeEnd)
  window.removeEventListener('pointercancel', onResizeEnd)
  persistWindowRect()
}

function handleViewportResize() {
  viewport.value = { width: window.innerWidth, height: window.innerHeight }
  // 嵌入式模式不读写窗口位置存储：它的尺寸由宿主容器决定。
  if (props.embedded) return
  windowRect.value = clampWindowRect(windowRect.value, layoutContext.value)
  persistWindowRect()
}

/**
 * 测量聊天面板自身的渲染宽度。
 *
 * 只用于双栏断点判断，**不能**写回 `viewport`：`viewport.width` 表示浏览器
 * 视口，是窗口缩放上限（maxWidth）的计算依据；一旦把它覆盖成面板宽度，
 * 缩放会形成自反馈——窗口 430px 时视口被当成 430，于是
 * `availableWidth = 414`、`minWidth` 被压到 240，拖拽反而把窗口缩到 240px。
 */
function measurePanelWidth() {
  const element = panelRef.value || rootRef.value
  const width = element?.clientWidth || 0
  if (width > 0) {
    panelWidth.value = width
  }
}

function persistWindowRect() {
  try {
    globalThis.localStorage?.setItem(
      windowStorageKey.value,
      serializeWindowRect(windowRect.value),
    )
  } catch {
    // localStorage 不可用（隐私模式等）时静默跳过持久化。
  }
}

function restoreWindowRect(): WindowRect {
  try {
    const restored = parseWindowRect(
      globalThis.localStorage?.getItem(windowStorageKey.value) ?? null,
    )
    if (restored) return clampWindowRect(restored, layoutContext.value)
  } catch {
    // 持久化读取异常时回退到默认布局。
  }
  return defaultWindowRect(layoutContext.value)
}

async function handleSend(text: string, attachments?: any[]) {
  if (isSending.value) return
  isSending.value = true
  await agent.sendMessage(text, attachments ? { attachments } : undefined)
}

async function handleUploadAttachment(file: File) {
  try {
    const result = await agent.uploadAsset(file)
    if (chatInputRef.value) {
      chatInputRef.value.updateAttachment(
        // 找到匹配的 pending attachment
        chatInputRef.value.getAttachments().find((a: any) => a.filename === file.name && a.state === 'pending')?.id || '',
        { state: 'ready', assetId: result.assetId }
      )
    }
  } catch (error) {
    if (chatInputRef.value) {
      const pending = chatInputRef.value.getAttachments().find((a: any) => a.filename === file.name && a.state === 'pending')
      if (pending) {
        chatInputRef.value.updateAttachment(pending.id, { state: 'failed', errorMessage: error instanceof Error ? error.message : '上传失败' })
      }
    }
  }
}

function handleStop() {
  agent.cancelMessage()
  isSending.value = false
  pendingMessage.value = null
  pendingLoop.value = null
}

function handleButtonClick(value: string) {
  handleSend(value)
}

/** 拉取会话列表；失败时保留旧列表并展示可重试的错误提示。 */
async function loadConversations() {
  if (!isDesktop.value) return
  conversationsLoading.value = true
  conversationsError.value = ''
  try {
    const page = await agent.listConversations()
    conversations.value = page.items
  } catch (error) {
    conversationsError.value = error instanceof Error ? error.message : '会话列表加载失败'
  } finally {
    conversationsLoading.value = false
  }
}

function handleSelectConversation(id: number) {
  void (async () => {
    try {
      await agent.openConversation(id)
      activeConversationId.value = String(id)
      sidebarOpen.value = false
    } catch (error) {
      conversationsError.value = error instanceof Error ? error.message : '会话打开失败'
    }
  })()
}

function handleCreateConversation() {
  // startNewConversation 会发出 conversations_changed，列表由事件统一刷新。
  agent.startNewConversation()
  activeConversationId.value = undefined
  sidebarOpen.value = false
}

function handleDeleteConversation(id: number) {
  void (async () => {
    try {
      await agent.deleteConversation(id)
      if (activeConversationId.value === String(id)) {
        activeConversationId.value = undefined
      }
      // 列表刷新同样交给 conversations_changed，避免重复请求。
    } catch (error) {
      conversationsError.value = error instanceof Error ? error.message : '会话删除失败'
    }
  })()
}

/** 会话列表变化（新建 / 首条消息 / 回答完成 / 删除）后刷新侧栏。 */
function handleConversationsChanged() {
  // 事件可能先于 client 同步会话 ID 到达，这里重新对齐高亮项。
  activeConversationId.value = agent.currentConversationId
  void loadConversations()
}

function handleMessage(_msg: Message) {
  messages.value = agent.getMessages()
  pendingMessage.value = null
  pendingLoop.value = null
  isSending.value = false
  // 首条消息发出后后端才创建会话，这里同步当前高亮项。
  // 列表本身的新增/更新由 client 的 conversations_changed 事件驱动，
  // 不在这里重复拉取，避免流式期间反复请求列表接口。
  activeConversationId.value = agent.currentConversationId
}

function handleHistoryCleared() {
  messages.value = []
  pendingMessage.value = null
  pendingLoop.value = null
  pendingConfirmation.value = null
  pendingQuestion.value = null
  isSending.value = false
}

function handleMessageUpdating(data: { id: string; text: string; timeline?: AssistantTimelineEntry[]; loop?: import('../../core').AgentLoopRun }) {
  // AgentLoop 事件可能晚于首个正文 delta；先给用户一个可持续更新的思考状态。
  const loop = data.loop || pendingLoop.value || pendingMessage.value?.loop || {
    id: `pending-${data.id}`,
    requestId: '',
    status: 'running' as const,
    summary: '正在处理请求',
    steps: []
  }
  pendingMessage.value = {
    ...data,
    loop
  }

  pendingLoop.value = loop
  isSending.value = true
}

function handleAgentLoop(loop: import('../../core').AgentLoopRun) {
  pendingLoop.value = { ...loop, steps: [...loop.steps] }
  if (!pendingMessage.value && loop.status === 'running') {
    pendingMessage.value = {
      id: `loop-${loop.id}`,
      text: '',
      loop: pendingLoop.value
    }
  }
  if (pendingMessage.value) {
    pendingMessage.value = {
      ...pendingMessage.value,
      loop: pendingLoop.value
    }
  }
  isSending.value = loop.status === 'running'
}

function handleConnectionStateChange(state: ConnectionState) {
  connectionState.value = state
  if (state === 'disconnected' || state === 'error') {
    pendingConfirmation.value = null
    pendingQuestion.value = null
  }
}

function handleConfirmationRequired(value: ToolConfirmationData) {
  if (hasCustomConfirmationHandler.value) return
  pendingConfirmation.value = value
}

function handleConfirmationResolved(value: { callId: string }) {
  if (pendingConfirmation.value?.callId === value.callId) {
    pendingConfirmation.value = null
  }
}

function handleQuestionRequired(value: AgentQuestion) {
  if (hasCustomQuestionHandler.value) return
  pendingQuestion.value = value
}

function handleQuestionResolved(value: { questionId: string }) {
  if (pendingQuestion.value?.questionId === value.questionId) {
    pendingQuestion.value = null
  }
}

onMounted(() => {
  isOpen.value = props.embedded
  viewport.value = { width: window.innerWidth, height: window.innerHeight }
  if (!props.embedded) {
    windowRect.value = restoreWindowRect()
    window.addEventListener('resize', handleViewportResize)
  } else {
    window.addEventListener('resize', handleViewportResize)
  }
  // 两种模式都观察面板本身：embedded 看宿主容器，floating 看悬浮窗
  // （拖拽/缩放改变宽度后，双栏断点要跟着重新判断）。
  attachPanelObserver()

  messages.value = agent.getMessages()
  activeConversationId.value = agent.currentConversationId
  connectionState.value = agent.connectionState

  agent.on('message', handleMessage)
  agent.on('history_cleared', handleHistoryCleared)
  agent.on('message_updating', handleMessageUpdating)
  agent.on('agent_loop', handleAgentLoop)
  agent.on('connection_state', handleConnectionStateChange)
  agent.on('confirmation_required', handleConfirmationRequired)
  agent.on('confirmation_resolved', handleConfirmationResolved)
  agent.on('question_required', handleQuestionRequired)
  agent.on('question_resolved', handleQuestionResolved)
  agent.on('conversations_changed', handleConversationsChanged)
  agent.on('ui_open', open)
  agent.on('ui_close', close)
  agent.on('ui_toggle', () => {
    if (props.embedded) return
    isOpen.value = !isOpen.value
    // 面板刚出现时同样要测量宽度并建立观察器。
    if (isOpen.value) attachPanelObserver()
  })

  void loadConversations()
  agent.connect()
})

onUnmounted(() => {
  if (clearTimer) clearTimeout(clearTimer)
  clearTimer = null
  resizeObserver?.disconnect()
  resizeObserver = null
  window.removeEventListener('resize', handleViewportResize)
  onDragEnd()
  onResizeEnd()

  agent.off('message', handleMessage)
  agent.off('history_cleared', handleHistoryCleared)
  agent.off('message_updating', handleMessageUpdating)
  agent.off('agent_loop', handleAgentLoop)
  agent.off('connection_state', handleConnectionStateChange)
  agent.off('confirmation_required', handleConfirmationRequired)
  agent.off('confirmation_resolved', handleConfirmationResolved)
  agent.off('question_required', handleQuestionRequired)
  agent.off('question_resolved', handleQuestionResolved)
  agent.off('conversations_changed', handleConversationsChanged)
  pendingConfirmation.value = null
  pendingQuestion.value = null
  agent.disconnect()
})

// 注册自定义组件
function registerCustomComponent(name: string, component: Component) {
  customComponents.value[name] = component
}

// 暴露给外部
defineExpose({
  registerCustomComponent
})
</script>

<style>
@import '../styles/index.css';
</style>
