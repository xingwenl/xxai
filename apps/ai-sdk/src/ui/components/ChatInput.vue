<template>
  <div class="xxai-chat-input-wrapper">
    <div class="xxai-chat-input">
      <input
        v-model="inputText"
        type="text"
        placeholder="输入消息..."
        @keydown.enter="handleSend"
        :disabled="isSending"
      />
      <button v-if="!isSending" class="xxai-send-button" aria-label="发送消息" @click="handleSend" :disabled="!inputText.trim()">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4.5 20 12 4 19.5 7 12 4 4.5Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M7 12h9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
      </button>
      <button v-else class="xxai-stop-button" type="button" aria-label="停止生成" @click="$emit('stop')"><span></span></button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

interface Props {
  isSending?: boolean
}

const { isSending = false } = defineProps<Props>();

const emit = defineEmits<{
  send: [text: string]
  stop: []
}>()

const inputText = ref('')

function handleSend() {
  const text = inputText.value.trim()
  if (text) {
    emit('send', text)
    inputText.value = ''
  }
}
</script>
