<template>
  <div class="xxai-message" :class="message.role">
    <div class="xxai-message-content">
      <component
        v-if="isCustomComponent"
        :is="getCustomComponent((message.content as any).componentName)"
        v-bind="(message.content as any).props"
      />
      <template v-else>
        <img v-if="message.content.type === 'image'" :src="(message.content as any).url" :alt="(message.content as any).alt" />
        <div v-else-if="message.content.type === 'text_with_buttons'">
          <p>{{ (message.content as any).text }}</p>
          <div class="xxai-buttons">
            <button
              v-for="btn in (message.content as any).buttons"
              :key="btn.value"
              @click="handleButtonClick(btn)"
            >
              {{ btn.text }}
            </button>
          </div>
        </div>
        <p v-else>{{ displayText }}</p>
        <CitationList v-if="message.metadata?.citations" :citations="message.metadata.citations as Array<{ title?: string; text?: string; sourceUrl?: string }>" />
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, h } from 'vue'
import type { Message, TextContent } from '../../core'
import CitationList from './CitationList.vue'

interface Props {
  message: Message
}

const props = defineProps<Props>()

const emit = defineEmits<{
  buttonClick: [value: string]
}>()

const pendingText = ref<string | null>(null)

function updatePendingText(text: string) {
  pendingText.value = text
}

const displayText = computed(() => {
  if (pendingText.value !== null) {
    return pendingText.value
  }
  const content = props.message.content as TextContent
  return content.text || ''
})

const isCustomComponent = computed(() => {
  return props.message.content.type === 'custom'
})

function getCustomComponent(name: string) {
  // 这里应该从注册的自定义组件中获取
  return {
    render() {
      return h('div', `Custom component: ${name}`)
    }
  }
}

function handleButtonClick(btn: { value: string }) {
  emit('buttonClick', btn.value)
}

defineExpose({
  updatePendingText
})
</script>

<style scoped>
.xxai-buttons {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.xxai-buttons button {
  padding: 6px 12px;
  border: 1px solid #667eea;
  background: white;
  color: #667eea;
  border-radius: 16px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}

.xxai-buttons button:hover {
  background: #667eea;
  color: white;
}

img {
  max-width: 100%;
  border-radius: 8px;
}

p {
  margin: 0;
}
</style>
