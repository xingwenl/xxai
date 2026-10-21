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
        'xxai-chat-window--sidebar-drawer': isSidebarDrawer,
        'xxai-chat-window--drawer-open': isSidebarDrawer && sidebarOpen
      }"
      :style="windowStyle"
    >
      <ConversationSidebar
        v-if="isDesktop"
        :collapsed="isSidebarWidthCollapsed"
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
      <!-- 窄屏抽屉的遮罩：点击关闭列表，避免遮挡对话区。
           常驻挂载以便用透明度淡入淡出，关闭态由 CSS 关闭点击拦截。 -->
      <div
        v-if="isSidebarDrawer"
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
        <div class="xxai-header-center">
          <!-- 会话列表开关（头像左侧）：宽屏收起/展开常驻列表，窄屏展开抽屉。 -->
          <button
            v-if="isDesktop"
            class="xxai-header-icon-btn xxai-sidebar-toggle"
            type="button"
            :aria-label="sidebarToggleLabel"
            :title="sidebarToggleLabel"
            :aria-expanded="isSidebarVisible"
            @click="toggleSidebar"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="4" width="18" height="16" rx="2.5" />
              <path d="M9.5 4v16" />
              <path :d="isSidebarVisible ? 'm15.5 9.5-3 2.5 3 2.5' : 'm12.5 9.5 3 2.5-3 2.5'" />
            </svg>
          </button>
          <div class="xxai-agent-avatar" aria-hidden="true">✦</div>
          <div class="xxai-header-info">
            <!-- 标题行：后台开启切换且宿主给了多个候选时，整行变成下拉入口。 -->
            <button
              v-if="agentSwitcherVisible"
              class="xxai-header-name xxai-header-name--switchable"
              type="button"
              aria-haspopup="listbox"
              :aria-expanded="switcherOpen"
              :aria-label="`当前智能体：${agentName}，点击切换`"
              :title="agentSwitcherTitle"
              @click.stop="toggleAgentSwitcher"
            >
              <span class="xxai-header-name-text">{{ agentName }}</span>
              <svg class="xxai-agent-switch-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="m6 9 6 6 6-6" />
              </svg>
            </button>
            <div v-else class="xxai-header-name">{{ headerName }}</div>
            <!-- role=status：连接状态变化对屏幕阅读器可感知（polite 播报）。 -->
            <div class="xxai-header-status" :class="`is-${connectionState}`" role="status">
              <span class="xxai-status-dot"></span>
              <span>{{ statusText }}</span>
            </div>
            <!-- 候选列表：绝对定位浮在聊天区上方，不挤压头部布局。 -->
            <div
              v-if="switcherOpen"
              class="xxai-agent-switcher"
              role="listbox"
              aria-label="选择智能体"
              @pointerdown.stop
            >
              <div v-if="switcherHint" class="xxai-agent-switcher-hint" role="status">
                {{ switcherHint }}
              </div>
              <button
                v-for="option in agentSwitchOptions"
                :key="option.agentId"
                class="xxai-agent-switch-option"
                :class="{ 'is-active': String(option.agentId) === agent.currentAgentId }"
                type="button"
                role="option"
                :aria-selected="String(option.agentId) === agent.currentAgentId"
                :disabled="switcherBusy"
                @click.stop="selectAgent(option)"
              >
                <span class="xxai-agent-switch-option-text">
                  <span class="xxai-agent-switch-option-name">{{ option.name }}</span>
                  <span v-if="option.description" class="xxai-agent-switch-option-desc">{{ option.description }}</span>
                </span>
                <svg
                  v-if="String(option.agentId) === agent.currentAgentId"
                  class="xxai-agent-switch-check"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2.4"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                >
                  <path d="m5 13 4 4L19 7" />
                </svg>
                <span
                  v-else-if="switchingAgentId === String(option.agentId)"
                  class="xxai-agent-switch-spinner"
                  aria-hidden="true"
                />
              </button>
            </div>
          </div>
          <!-- 上下文占用环：与连接状态同排，让用户一眼看到当前会话离窗口上限多远。
               窗口大小未知时（contextRing 为 null）降级为只显示绝对 token 数。 -->
          <ContextRing
            v-if="contextRing"
            class="xxai-header-context"
            :state="contextRing"
            :title="contextTitle"
          />
          <span
            v-else-if="contextUsage"
            class="xxai-header-context-text"
            :title="contextTitle"
          >{{ contextTokensText }}</span>
        </div>
        <!-- <QuotaRing
          class="xxai-header-quota"
          :current="messageQuota?.current"
          :limit="messageQuota?.limit"
          :window-seconds="quota?.windowSeconds"
        /> -->
        <!-- 手动压缩：后端会在压缩完成后推送 context_compacted，环随之刷新。 -->
        <button
          class="xxai-header-icon-btn xxai-header-compact-btn"
          :class="{ 'has-feedback': !!compactFeedback }"
          type="button"
          :disabled="compacting"
          :aria-label="compactButtonTitle"
          :title="compactButtonTitle"
          @click="handleCompactContext"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 4h16M4 20h16M12 7v7M9 11l3 3 3-3" />
          </svg>
        </button>
        <button
          class="xxai-header-icon-btn xxai-header-clear-btn"
          type="button"
          :aria-label="isClearPending(CLEAR_HISTORY_KEY) ? '确认清除聊天记录' : '清除聊天记录'"
          @click="onClearClick"
        >
          <span v-if="isClearPending(CLEAR_HISTORY_KEY)" class="xxai-clear-confirm">确认？</span>
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
        :show-agent-steps="showAgentSteps"
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
import ContextRing from './ContextRing.vue'
import ConversationSidebar from './ConversationSidebar.vue'
import type {
  AgentClient,
  AgentInfo,
  AgentQuestion,
  AgentSwitchFailedEvent,
  AgentSwitchOption,
  AgentSwitchedEvent,
  AssistantTimelineEntry,
  ConnectionState,
  ContextUsage,
  ConversationSummary,
  EmbedClientInfo,
  QuotaUsage,
  UIOptions,
  Message,
  UIColors,
  UIWindowBounds,
  ToolConfirmation as ToolConfirmationData
} from '../../core'
import { contextRingState, formatTokens } from '../context-ring'
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
import { useTwoStepConfirm } from '../two-step-confirm'

/** 「清除聊天记录」这个固定动作在二次确认状态机里的目标标识。 */
const CLEAR_HISTORY_KEY = 'clear-history'

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
  /** 是否渲染 Agent 过程卡片；缺省 false，只保留对话正文。 */
  showAgentSteps?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  position: 'right',
  theme: 'auto',
  title: 'AI Assistant',
  embedded: false,
  layout: 'single',
  sidebarWidth: 260,
  showAgentSteps: false
})

const isOpen = ref(false)
const isSending = ref(false)
const messages = ref<Message[]>([])
const conversations = ref<ConversationSummary[]>([])
const conversationsLoading = ref(false)
const conversationsError = ref('')
const sidebarOpen = ref(false)
/** 宽屏下用户手动收起左侧列表；与窄屏抽屉开关分开，互不覆盖。 */
const sidebarCollapsed = ref(false)
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
const rootRef = ref<HTMLElement | null>(null)
/** 聊天面板本身：双栏断点按它的宽度判断，而非浏览器视口。 */
const panelRef = ref<HTMLElement | null>(null)
const {
  isPending: isClearPending,
  confirm: confirmClearClick,
  cancel: cancelClearConfirm
} = useTwoStepConfirm()
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
/**
 * 会话列表当前是否可见。
 *
 * 两种形态共用一个开关入口但状态彼此独立：宽屏看「是否被手动收起」，
 * 窄屏看「抽屉是否展开」，因此面板宽度在断点两侧来回变化时不会互相污染。
 */
const isSidebarVisible = computed(() => {
  if (!isDesktop.value) return false
  return isNarrow.value ? sidebarOpen.value : !sidebarCollapsed.value
})
/** 窄屏抽屉形态：列表浮在对话区之上，用位移动画开合。 */
const isSidebarDrawer = computed(() => isDesktop.value && isNarrow.value)
/**
 * 只有宽屏的常驻列表才走「宽度收缩」路径。
 *
 * 窄屏抽屉靠 transform 滑出，若这时也打上收起类，两套动画会互相打架
 * （宽度归零 + 位移），列表会以奇怪的方式塌掉。
 */
const isSidebarWidthCollapsed = computed(
  () => isDesktop.value && !isNarrow.value && sidebarCollapsed.value
)
const sidebarToggleLabel = computed(() =>
  isSidebarVisible.value ? '隐藏会话列表' : '显示会话列表'
)

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
// agent 的 client/agent/quota 都是非响应式 getter：session_ready 晚到时模板
// 不会刷新，因此订阅 client_info 并同步一份 ref 给模板消费。
const clientInfo = ref<EmbedClientInfo | undefined>(agent.clientInfo)
const agentInfo = ref<AgentInfo | undefined>(agent.agentInfo)
const quota = ref<QuotaUsage | undefined>(agent.quota)
const headerName = computed(() => resolveHeaderName(clientInfo.value?.name, props.title))
const messageQuota = computed(() => quota.value?.resources?.message)
const agentName = computed(() => agentInfo.value?.name || props.title)
const agentDescription = computed(() => agentInfo.value?.description || undefined)

// ---------------------------------------------------------------------------
// 智能体切换：开关由后台 embed client 经 session_ready 下发，候选由宿主传入。
// 只有「后台开启 + 本地未禁用 + 候选超过 1 个」才渲染入口，见 ADR 0014。
// ---------------------------------------------------------------------------
/** 下拉候选面板是否展开。 */
const switcherOpen = ref(false)
/** 正在切换的目标 agent id（字符串），用于选项上的 loading 态与防重复点击。 */
const switchingAgentId = ref<string | null>(null)
/** 失败/忙碌的内联提示；5 秒后自动消失，避免长期占用头部空间。 */
const switcherHint = ref('')
let switcherHintTimer: ReturnType<typeof setTimeout> | null = null

const agentSwitchOptions = computed<AgentSwitchOption[]>(() => agent.availableAgents)
const agentSwitcherVisible = computed(
  () =>
    clientInfo.value?.allowAgentSwitching === true &&
    agentSwitchOptions.value.length > 1
)
/** 忙碌判定与 client 内部一致：生成中、待确认、待回答都不能重建连接。 */
const switcherBusy = computed(
  () =>
    isSending.value ||
    Boolean(pendingConfirmation.value) ||
    Boolean(pendingQuestion.value) ||
    switchingAgentId.value !== null
)
const agentSwitcherTitle = computed(() => {
  if (switchingAgentId.value) return '正在切换智能体…'
  if (switcherBusy.value) return '正在生成回答，请稍后再切换'
  return `切换智能体（当前：${agentName.value}）`
})

function clearSwitcherHint() {
  switcherHint.value = ''
  if (switcherHintTimer) {
    clearTimeout(switcherHintTimer)
    switcherHintTimer = null
  }
}

function showSwitcherHint(message: string) {
  switcherHint.value = message
  if (switcherHintTimer) clearTimeout(switcherHintTimer)
  switcherHintTimer = setTimeout(() => {
    switcherHint.value = ''
    switcherHintTimer = null
  }, 5000)
}

function toggleAgentSwitcher() {
  if (!agentSwitcherVisible.value) return
  switcherOpen.value = !switcherOpen.value
  if (!switcherOpen.value) clearSwitcherHint()
}

/**
 * 切换入口：成功由 `agent_switched` 收尾（关闭面板、刷新标题与会话），
 * 失败由 `agent_switch_failed` 收尾（保留面板与提示），这里只维护进行态。
 */
function selectAgent(option: AgentSwitchOption) {
  if (switcherBusy.value) return
  if (String(option.agentId) === agent.currentAgentId) {
    switcherOpen.value = false
    clearSwitcherHint()
    return
  }
  clearSwitcherHint()
  switchingAgentId.value = String(option.agentId)
  void agent
    .switchAgent(option.agentId)
    .then((ok) => {
      if (!ok && !switcherHint.value) {
        showSwitcherHint('切换智能体失败，请稍后重试')
      }
    })
    .finally(() => {
      switchingAgentId.value = null
    })
}

function handleAgentSwitched(event: AgentSwitchedEvent) {
  switchingAgentId.value = null
  switcherOpen.value = false
  clearSwitcherHint()
  // client 会清空并恢复目标 agent 的本地会话，这里同步 UI 侧快照。
  pendingMessage.value = null
  pendingLoop.value = null
  isSending.value = false
  if (event.agent) agentInfo.value = event.agent
  messages.value = agent.getMessages()
  activeConversationId.value = agent.currentConversationId
  void loadConversations()
}

function handleAgentSwitchFailed(event: AgentSwitchFailedEvent) {
  switchingAgentId.value = null
  showSwitcherHint(event.message)
  // 预签失败时 client 什么都没改，但同步一次可避免半途状态残留到 UI。
  messages.value = agent.getMessages()
  activeConversationId.value = agent.currentConversationId
}

/** 点击面板外部收起；在 rootRef 内点击交给各按钮自己的处理。 */
function handleDocumentPointerDown(event: PointerEvent) {
  if (!switcherOpen.value) return
  const target = event.target as Node | null
  if (target && rootRef.value?.contains(target)) return
  switcherOpen.value = false
  clearSwitcherHint()
}

function handleDocumentKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && switcherOpen.value) {
    switcherOpen.value = false
    clearSwitcherHint()
  }
}

/** 上下文占用快照：同样在事件里同步，确保 header 的环随推送刷新。 */
const contextUsage = ref<ContextUsage | null>(agent.contextUsage)
const contextRing = computed(() =>
  contextUsage.value
    ? contextRingState(contextUsage.value.usedTokens, contextUsage.value.windowTokens)
    : null
)
const contextTokensText = computed(() =>
  contextUsage.value ? formatTokens(contextUsage.value.usedTokens) : ''
)
const contextTitle = computed(() => {
  if (!contextUsage.value) return ''
  if (!contextRing.value) {
    return `上下文已用 ${contextTokensText.value}（模型窗口大小未知，无法估算百分比）`
  }
  // 环旁边只显示百分比，绝对量放在提示里，兼顾「一眼扫」与「核对口径」。
  const detail = `上下文已用 ${contextRing.value.text}（${contextRing.value.detail}）`
  const compactedAt = contextUsage.value.lastCompactedAt
  return compactedAt ? `${detail}；上次压缩：${compactedAt}` : detail
})

/** 手动压缩是否进行中（进行中禁用按钮，避免重复请求）。 */
const compacting = ref(false)
/** 压缩失败或空操作的可见反馈；下一次请求开始时清空。 */
const compactFeedback = ref('')
const compactButtonTitle = computed(() => {
  if (compacting.value) return '正在压缩上下文…'
  if (compactFeedback.value) return `压缩上下文：${compactFeedback.value}`
  return '压缩上下文'
})

function handleClientInfo(payload: {
  client?: EmbedClientInfo
  agent?: AgentInfo
  quota?: QuotaUsage
}) {
  clientInfo.value = payload.client
  agentInfo.value = payload.agent
  quota.value = payload.quota
}

function handleContextUsage(usage: ContextUsage) {
  contextUsage.value = usage
}

function handleContextCompacted() {
  // client 已按压缩结果更新过状态，这里直接取最新快照，不重复解析 payload。
  contextUsage.value = agent.contextUsage
}

/**
 * 手动触发一次服务端压缩。
 *
 * 失败与「无可压缩内容」都不能变成未捕获异常（按钮点击会冒泡到宿主页面），
 * 统一落成按钮 title 里的反馈文案，同时给按钮加高亮类，鼠标不悬停也看得见。
 */
async function handleCompactContext() {
  if (compacting.value) return
  compacting.value = true
  compactFeedback.value = ''
  try {
    const result = await agent.compactContext()
    if (!result) {
      compactFeedback.value = '服务端未返回压缩结果'
    } else if (!result.compacted) {
      compactFeedback.value =
        result.reason === 'nothing_to_compact' ? '没有可压缩的内容' : result.reason || '未发生压缩'
    } else if (!result.ok) {
      compactFeedback.value = result.reason || '压缩失败'
    }
  } catch (error) {
    compactFeedback.value = error instanceof Error ? error.message : String(error)
  } finally {
    compacting.value = false
  }
}

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

/** 「清除聊天记录」需点两次：第一次点出「确认？」，3 秒内再点才真正清除。 */
function onClearClick() {
  if (!confirmClearClick(CLEAR_HISTORY_KEY)) return
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

/**
 * 会话列表开关（header 头像右侧按钮）。
 *
 * 宽屏收放常驻列表，窄屏开合抽屉；不可见的形态直接忽略本次点击。
 */
function toggleSidebar() {
  if (!isDesktop.value) return
  if (isNarrow.value) {
    sidebarOpen.value = !sidebarOpen.value
    return
  }
  sidebarCollapsed.value = !sidebarCollapsed.value
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
  // client_info 之前没订阅：会话/配额晚于挂载下发时 header 一直是初始值。
  agent.on('client_info', handleClientInfo)
  agent.on('context_usage', handleContextUsage)
  agent.on('context_compacted', handleContextCompacted)
  agent.on('agent_switched', handleAgentSwitched)
  agent.on('agent_switch_failed', handleAgentSwitchFailed)
  // 智能体下拉的「点外部/按 Esc 收起」挂在 document 上：面板是绝对定位浮层，
  // 点聊天区其它位置时也要能收起。
  document.addEventListener('pointerdown', handleDocumentPointerDown)
  document.addEventListener('keydown', handleDocumentKeydown)
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
  cancelClearConfirm()
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
  agent.off('client_info', handleClientInfo)
  agent.off('context_usage', handleContextUsage)
  agent.off('context_compacted', handleContextCompacted)
  agent.off('agent_switched', handleAgentSwitched)
  agent.off('agent_switch_failed', handleAgentSwitchFailed)
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
  document.removeEventListener('keydown', handleDocumentKeydown)
  if (switcherHintTimer) {
    clearTimeout(switcherHintTimer)
    switcherHintTimer = null
  }
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
