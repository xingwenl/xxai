<template>
  <div class="xxai-chat-messages" ref="messagesRef">
    <ChatBubble
      v-for="msg in messages"
      :key="msg.id"
      :message="msg"
      ref="bubbleRefs"
      @button-click="handleButtonClick"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, type ComponentPublicInstance } from 'vue'
import ChatBubble from './ChatBubble.vue'
import type { Message } from '../../core'

interface Props {
  messages: Message[]
  pendingMessage?: { id: string; text: string } | null
}

const props = defineProps<Props>()

const emit = defineEmits<{
  buttonClick: [value: string]
}>()

const messagesRef = ref<HTMLElement | null>(null)
const bubbleRefs = ref<(ComponentPublicInstance | null)[]>([])

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
      const index = props.messages.findIndex((m) => m.id === newPending.id)
      if (index !== -1 && bubbleRefs.value[index]) {
        const bubble = bubbleRefs.value[index] as any
        bubble?.updatePendingText?.(newPending.text)
      }
      scrollToBottom()
    }
  }
)

function handleButtonClick(value: string) {
  emit('buttonClick', value)
}
</script>
