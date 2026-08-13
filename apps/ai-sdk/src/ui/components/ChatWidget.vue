<template>
  <div class="xxai-reset">
    <FloatingButton v-if="!isOpen" :position="position" @click="open" />
    <div v-if="isOpen" class="xxai-chat-window" :class="{ left: position === 'left', dark: theme === 'dark' }" :style="colorStyle">
      <div class="xxai-chat-header">
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
  ToolConfirmation as ToolConfirmationData
} from '../../core'

interface Props {
  agent: AgentClient
  position?: UIOptions['position']
  theme?: UIOptions['theme']
  title?: string
  colors?: UIColors
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
  messages.value = agent.getMessages()
  connectionState.value = agent.connectionState

  agent.on('message', handleMessage)
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
  agent.off('message', handleMessage)
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
