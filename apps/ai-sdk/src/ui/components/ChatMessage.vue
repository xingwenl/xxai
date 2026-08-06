<template>
  <article class="xxai-chat-message" :class="message.role">
    <div v-if="message.role === 'user'" class="xxai-user-message">
      <MessageContent :blocks="contentBlocks" @action="handleAction" />
    </div>
    <div v-else class="xxai-assistant-message">
      <div class="xxai-assistant-row">
        <div class="xxai-agent-avatar" aria-hidden="true">✦</div>
        <div class="xxai-assistant-content">
          <TypingIndicator v-if="pending && !hasRenderableContent && !message.loop" />
          <MessageContent
            v-else-if="hasRenderableContent"
            :blocks="contentBlocks"
            @action="handleAction"
          />
          <AgentLoopPanel :message="message" />
        </div>
      </div>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Message, MessageContentBlock } from '../../core'
import AgentLoopPanel from './AgentLoopPanel.vue'
import MessageContent from './MessageContent.vue'
import TypingIndicator from './TypingIndicator.vue'
import { hasRenderableMessageContent } from '../message-presentation'

const props = defineProps<{
  message: Message
  pending?: boolean
}>()
const emit = defineEmits<{ buttonClick: [value: string] }>()
const contentBlocks = computed<MessageContentBlock[]>(() => props.message.contentBlocks?.length
  ? props.message.contentBlocks
  : [{
      id: `${props.message.id}-text`,
      type: 'markdown',
      text: String((props.message.content as { text?: string }).text || ''),
      status: 'completed'
    }])
const hasRenderableContent = computed(() => hasRenderableMessageContent(contentBlocks.value))

function handleAction(value: string) {
  emit('buttonClick', value)
}
</script>
