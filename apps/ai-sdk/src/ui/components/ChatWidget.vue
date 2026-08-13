<template>
  <div class="xxai-reset">
    <FloatingButton v-if="!isOpen" :position="position" @click="open" />
    <div v-if="isOpen" class="xxai-chat-window" :class="{ dark: theme === 'dark' }" :style="windowStyle">
      <div class="xxai-chat-header xxai-chat-window-drag" @pointerdown="startDrag">
        <button class="xxai-header-icon-btn" type="button" aria-label="返回" @click="close">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="m15 18-6-6 6-6" />
          </svg>
        </button>
        <div class="xxai-header-center">
          <div class="xxai-agent-avatar" aria-hidden="true">✦</div>
          <div class="xxai-header-info">
            <div class="xxai-header-name">{{ title }}</div>
            <div class="xxai-header-status">
              <span class="xxai-status-dot"></span>
              <span>{{ statusText }}</span>
            </div>
          </div>
        </div>
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
        <button class="xxai-header-icon-btn" type="button" aria-label="关闭" @click="close">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>
      <ChatMessageList
        :messages="messages"
        :pending-message="pendingMessage"
        @button-click="handleButtonClick"
      />
      <ToolConfirmation
        v-if="pendingConfirmation && !hasCustomConfirmationHandler"
        :key="pendingConfirmation.callId"
        :agent="agent"
        :confirmation="pendingConfirmation"
      />
      <ChatInput :is-sending="isSending" @send="handleSend" @stop="handleStop" />
      <div
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
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, type Component } from 'vue'
import FloatingButton from './FloatingButton.vue'
import ChatMessageList from './ChatMessageList.vue'
import ChatInput from './ChatInput.vue'
import ToolConfirmation from './ToolConfirmation.vue'
import type {
  AgentClient,
  AssistantTimelineEntry,
  ConnectionState,
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
import { parseWindowRect, serializeWindowRect } from '../window-storage'

interface Props {
  agent: AgentClient
  position?: UIOptions['position']
  theme?: UIOptions['theme']
  title?: string
  colors?: UIColors
  window?: UIWindowBounds
}

const props = withDefaults(defineProps<Props>(), {
  position: 'right',
  theme: 'auto',
  title: 'AI Assistant'
})

const isOpen = ref(false)
const isSending = ref(false)
const messages = ref<Message[]>([])
const pendingMessage = ref<{ id: string; text: string; timeline?: AssistantTimelineEntry[]; loop?: import('../../core').AgentLoopRun } | null>(null)
const pendingLoop = ref<import('../../core').AgentLoopRun | null>(null)
const connectionState = ref<ConnectionState>('disconnected')
const customComponents = ref<Record<string, Component>>({})
const pendingConfirmation = ref<ToolConfirmationData | null>(null)
const viewport = ref({ width: 0, height: 0 })
const windowRect = ref<WindowRect>({ x: 0, y: 0, width: 430, height: 680 })
const confirmClear = ref(false)
let clearTimer: ReturnType<typeof setTimeout> | null = null

const agent = props.agent
const hasCustomConfirmationHandler = computed(() => Boolean(agent.callbacks.onConfirmationRequired))
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
  ...colorStyle.value,
  left: `${windowRect.value.x}px`,
  top: `${windowRect.value.y}px`,
  width: `${windowRect.value.width}px`,
  height: `${windowRect.value.height}px`,
}))
const windowStorageKey = computed(() => `${agent.storageKey}:window`)

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

function open() {
  isOpen.value = true
}

function close() {
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
  windowRect.value = clampWindowRect(windowRect.value, layoutContext.value)
  persistWindowRect()
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

async function handleSend(text: string) {
  if (isSending.value) return
  isSending.value = true
  await agent.sendMessage(text)
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

function handleMessage(_msg: Message) {
  messages.value = agent.getMessages()
  pendingMessage.value = null
  pendingLoop.value = null
  isSending.value = false
}

function handleHistoryCleared() {
  messages.value = []
  pendingMessage.value = null
  pendingLoop.value = null
  pendingConfirmation.value = null
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

onMounted(() => {
  viewport.value = { width: window.innerWidth, height: window.innerHeight }
  windowRect.value = restoreWindowRect()
  window.addEventListener('resize', handleViewportResize)

  messages.value = agent.getMessages()
  connectionState.value = agent.connectionState

  agent.on('message', handleMessage)
  agent.on('history_cleared', handleHistoryCleared)
  agent.on('message_updating', handleMessageUpdating)
  agent.on('agent_loop', handleAgentLoop)
  agent.on('connection_state', handleConnectionStateChange)
  agent.on('confirmation_required', handleConfirmationRequired)
  agent.on('confirmation_resolved', handleConfirmationResolved)
  agent.on('ui_open', open)
  agent.on('ui_close', close)
  agent.on('ui_toggle', () => {
    isOpen.value = !isOpen.value
  })

  agent.connect()
})

onUnmounted(() => {
  if (clearTimer) clearTimeout(clearTimer)
  clearTimer = null
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
  pendingConfirmation.value = null
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
