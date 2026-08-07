<template>
  <section class="xxai-tool-confirmation" role="alertdialog" aria-live="assertive">
    <div class="xxai-tool-confirmation-header">
      <span class="xxai-tool-confirmation-mark" aria-hidden="true">!</span>
      <div>
        <p class="xxai-tool-confirmation-eyebrow">需要确认</p>
        <h3>{{ confirmation.name }}</h3>
      </div>
    </div>
    <p class="xxai-tool-confirmation-copy">
      {{ riskText }}。允许后，AI 才会执行此工具。
    </p>
    <pre v-if="argumentsText" class="xxai-tool-confirmation-arguments">{{ argumentsText }}</pre>
    <p v-if="expired" class="xxai-tool-confirmation-expired">确认已过期，工具未执行。</p>
    <div v-else class="xxai-tool-confirmation-actions">
      <button type="button" class="xxai-tool-confirmation-reject" :disabled="submitting" @click="resolve(false)">
        拒绝
      </button>
      <button type="button" class="xxai-tool-confirmation-approve" :disabled="submitting" @click="resolve(true)">
        {{ submitting ? '处理中...' : '允许执行' }}
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import type { AgentClient, ToolConfirmation } from '../../core'

const props = defineProps<{
  agent: AgentClient
  confirmation: ToolConfirmation
}>()

const submitting = ref(false)
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | undefined

const expiresAt = computed(() => {
  if (!props.confirmation.expiresAt) return undefined
  const value = Date.parse(props.confirmation.expiresAt)
  return Number.isFinite(value) ? value : undefined
})
const expired = computed(() => expiresAt.value !== undefined && expiresAt.value <= now.value)
const argumentsText = computed(() => {
  const value = props.confirmation.summary?.arguments
  if (value === undefined) return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
})
const riskText = computed(() => {
  const labels: Record<string, string> = {
    navigation: '这是一个页面导航操作',
    write: '这是一个会修改数据的操作',
    financial: '这是一个可能影响资金的操作',
    external: '这是一个会影响外部系统的操作'
  }
  return labels[props.confirmation.sideEffect || ''] || '这是一个需要确认的操作'
})

if (expiresAt.value !== undefined) {
  timer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
}

function resolve(approved: boolean) {
  if (submitting.value || expired.value) return
  submitting.value = true
  props.agent.resolveToolCall(props.confirmation.callId, approved)
}

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>
