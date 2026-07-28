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
      <button v-if="!isSending" @click="handleSend" :disabled="!inputText.trim()">发送</button>
      <button v-else class="xxai-stop-button" type="button" @click="$emit('stop')">停止</button>
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
