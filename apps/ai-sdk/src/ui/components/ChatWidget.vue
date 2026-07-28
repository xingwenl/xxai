<template>
  <div class="xxai-reset">
    <FloatingButton v-if="!isOpen" :position="position" @click="open" />
    <div v-if="isOpen" class="xxai-chat-window" :class="{ left: position === 'left', dark: theme === 'dark' }">
      <div class="xxai-chat-header">
        <span class="xxai-chat-title">{{ title }}</span>
        <button class="xxai-chat-close" @click="close">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>
      </div>
      <div class="xxai-status" :class="connectionState">
        {{ statusText }}
      </div>
      <ChatMessageList
        :messages="messages"
        :pending-message="pendingMessage"
        @button-click="handleButtonClick"
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
import type { AgentClient, ConnectionState, UIOptions, Message } from '../../core'

interface Props {
  agent: AgentClient
  position?: UIOptions['position']
  theme?: UIOptions['theme']
  title?: string
}

const props = withDefaults(defineProps<Props>(), {
  position: 'right',
  theme: 'auto',
  title: 'AI Assistant'
})

const isOpen = ref(false)
const isSending = ref(false)
const messages = ref<Message[]>([])
const pendingMessage = ref<{ id: string; text: string } | null>(null)
const connectionState = ref<ConnectionState>('disconnected')
const customComponents = ref<Record<string, Component>>({})

const agent = props.agent

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
}

function handleButtonClick(value: string) {
  handleSend(value)
}

function handleMessage(_msg: Message) {
  messages.value = agent.getMessages()
  pendingMessage.value = null
  isSending.value = false
}

function handleMessageUpdating(data: { id: string; text: string }) {
  pendingMessage.value = data
  isSending.value = true
}

function handleConnectionStateChange(state: ConnectionState) {
  connectionState.value = state
}

onMounted(() => {
  messages.value = agent.getMessages()
  connectionState.value = agent.connectionState

  agent.on('message', handleMessage)
  agent.on('message_updating', handleMessageUpdating)
  agent.on('connection_state', handleConnectionStateChange)
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
  agent.off('connection_state', handleConnectionStateChange)
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
