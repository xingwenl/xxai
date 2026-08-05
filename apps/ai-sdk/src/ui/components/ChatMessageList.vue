<template>
  <div class="xxai-chat-messages" ref="messagesRef">
    <ChatMessage
      v-for="msg in messages"
      :key="msg.id"
      :message="msg"
      @button-click="handleButtonClick"
    />
    <ChatMessage
      v-if="pendingMessage"
      :message="pendingAsMessage"
      pending
      @button-click="handleButtonClick"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import ChatMessage from './ChatMessage.vue'
import type { Message, AgentLoopRun } from '../../core'

interface Props {
  messages: Message[]
  pendingMessage?: { id: string; text: string; loop?: import('../../core').AgentLoopRun } | null
}

const props = defineProps<Props>()

const emit = defineEmits<{
  buttonClick: [value: string]
}>()

const messagesRef = ref<HTMLElement | null>(null)
const pendingAsMessage = computed<Message>(() => ({
  id: props.pendingMessage?.id || 'pending',
  role: 'assistant',
  type: 'text',
  content: { type: 'text', text: props.pendingMessage?.text || '' },
  contentBlocks: [{
    id: props.pendingMessage?.id || 'pending',
    type: 'markdown',
    text: props.pendingMessage?.text || '',
    status: 'streaming'
  }],
  loop: props.pendingMessage?.loop as AgentLoopRun | undefined,
  timestamp: new Date()
}))

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

watch(
  () => props.messages.length,
  () => {
    scrollToBottom()
  }
)

watch(
  () => props.pendingMessage,
  (newPending) => {
    if (newPending) {
      scrollToBottom()
    }
  }
)

function handleButtonClick(value: string) {
  emit('buttonClick', value)
}
</script>
