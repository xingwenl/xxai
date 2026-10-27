<template>
  <div class="xxai-chat-messages" ref="messagesRef" @scroll.passive="handleScroll">
    <div
      v-if="messages.length === 0 && !pendingMessage"
      class="xxai-empty-state"
    >
      <div class="xxai-empty-avatar" aria-hidden="true">✦</div>
      <div v-if="agentName" class="xxai-empty-name">{{ agentName }}</div>
      <div v-if="agentDescription" class="xxai-empty-description">
        {{ agentDescription }}
      </div>
    </div>
    <ChatMessage
      v-for="msg in messages"
      :key="msg.id"
      :message="msg"
      :agent="props.agent"
      :show-agent-steps="showAgentSteps"
      @button-click="handleButtonClick"
    />
    <ChatMessage
      v-if="pendingMessage"
      :message="pendingAsMessage"
      :agent="props.agent"
      :show-agent-steps="showAgentSteps"
      pending
      @button-click="handleButtonClick"
    />
    <div
      v-if="sessionUsage"
      class="xxai-session-usage"
      :title="sessionUsage.detail"
    >
      {{ sessionUsage.text }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import ChatMessage from './ChatMessage.vue'
import type { AgentClient, AssistantTimelineEntry, Message, AgentLoopRun } from '../../core'
import { parseUsage, sumUsage } from '../../core'
import { isNearScrollBottom } from '../chat-scroll'
import { sessionUsageView } from '../usage-view'

interface Props {
  messages: Message[]
  pendingMessage?: { id: string; text: string; timeline?: AssistantTimelineEntry[]; loop?: import('../../core').AgentLoopRun } | null
  agentName?: string
  agentDescription?: string
  agent?: AgentClient
  /** 是否渲染 Agent 过程卡片；缺省 false，只保留对话正文。 */
  showAgentSteps?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  showAgentSteps: false
})

const emit = defineEmits<{
  buttonClick: [value: string]
}>()

// 会话累计 = 已加载消息的逐轮用量之和：与逐轮 chip 同源，不会出现两套数字。
const sessionUsage = computed(() =>
  sessionUsageView(sumUsage(props.messages.map((msg) => parseUsage(msg.metadata?.usage)))),
)

const messagesRef = ref<HTMLElement | null>(null)
const followsStream = ref(true)
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
  timeline: props.pendingMessage?.timeline,
  loop: props.pendingMessage?.loop as AgentLoopRun | undefined,
  timestamp: new Date()
}))

function scrollToBottom() {
  if (!followsStream.value) return
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

function handleScroll() {
  if (messagesRef.value) {
    followsStream.value = isNearScrollBottom(messagesRef.value)
  }
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

<style scoped>
.xxai-session-usage {
  align-self: center;
  padding: 2px 10px;
  color: var(--agent-muted-foreground);
  font-size: 11px;
  line-height: 1.8;
  text-align: center;
}
</style>
