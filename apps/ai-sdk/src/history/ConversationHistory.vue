<template>
  <div class="xxai-history-root xxai-history-thread">
    <div v-if="loading && messages.length === 0" class="xxai-history-hint xxai-history-hint--loading">
      {{ loadingText }}
    </div>

    <div v-else-if="error" class="xxai-history-hint xxai-history-hint--error">
      {{ error }}
    </div>

    <div v-else-if="messages.length === 0" class="xxai-history-hint xxai-history-hint--empty">
      {{ emptyText }}
    </div>

    <div v-else class="xxai-history-messages">
      <ChatMessage
        v-for="item in messages"
        :key="item.id"
        :message="item"
        :show-agent-steps="showAgentLoop"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import ChatMessage from '../ui/components/ChatMessage.vue'
import { mapHistoryMessages } from './map-history'
import type { Message } from '../core'
import type { ConversationHistorySource } from './types'

const props = withDefaults(
  defineProps<{
    source: ConversationHistorySource
    conversationId: number | string
    showAgentLoop?: boolean
    emptyText?: string
    loadingText?: string
  }>(),
  {
    showAgentLoop: true,
    emptyText: '暂无消息',
    loadingText: '加载中…'
  }
)

const emit = defineEmits<{
  loaded: [messages: Message[]]
  error: [error: unknown]
}>()

const messages = ref<Message[]>([])
const loading = ref(false)
const error = ref('')

/**
 * 拉取某个会话的完整消息并投影成 SDK `Message`。
 *
 * 映射走 `map-history.ts` 这份与 `AgentClient.fetchHistory()` 共用的实现，
 * 保证后台看到的 Loop 与 embed 聊天窗口同源（ADR 0003）。所有 await 都在
 * try/catch 内，失败只落地错误文案与 `error` 事件。
 *
 * `requestSeq` 用于丢弃过期响应：`conversationId` 快速切换时先发的请求可能
 * 后到，直接写入会把上一个会话的消息渲染到当前会话上。
 */
let requestSeq = 0
async function load(): Promise<void> {
  const seq = ++requestSeq
  loading.value = true
  error.value = ''
  try {
    const payloads = await props.source.listMessages(props.conversationId)
    if (seq !== requestSeq) return
    const mapped = mapHistoryMessages(
      Array.isArray(payloads) ? payloads : [],
      String(props.conversationId)
    )
    messages.value = mapped
    emit('loaded', mapped)
  } catch (err) {
    if (seq !== requestSeq) return
    messages.value = []
    error.value = err instanceof Error ? err.message : String(err)
    emit('error', err)
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

// immediate：挂载时即加载；`conversationId` 变化时重新加载，无需父组件手动触发。
watch(() => props.conversationId, () => void load(), { immediate: true })
</script>

<style scoped>
.xxai-history-thread {
  display: flex;
  flex-direction: column;
  min-height: 0;
  color: var(--agent-foreground, #0f172a);
  font-family: var(--agent-font-sans, inherit);
}

.xxai-history-hint {
  padding: 16px 12px;
  color: var(--agent-muted-foreground, #64748b);
  font-size: 13px;
}

.xxai-history-hint--error {
  color: #dc2626;
}

.xxai-history-hint--empty {
  text-align: center;
}

/*
 * 消息区的画布与聊天窗口保持一致：消息气泡用的是半透明磨砂白（--agent-card /
 * --agent-glass-surface），它需要底下那层很浅的彩色渐变才有对比，直接放在宿主
 * 的纯白背景上会显得发灰、发脏。这里只补「画布」这一层，气泡本身的样式一律
 * 交给既有组件，不做任何局部覆盖。
 */
.xxai-history-messages {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 12px;
  border-radius: var(--agent-radius-md);
  background: var(--agent-background-gradient);
  scrollbar-width: thin;
}
</style>
