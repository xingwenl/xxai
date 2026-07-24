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
      <button @click="handleSend" :disabled="isSending || !inputText.trim()">
        发送
      </button>
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
