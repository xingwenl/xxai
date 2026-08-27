<template>
  <div class="xxai-file-content">
    <a v-if="href" :href="href" :download="block.fileName || ''" target="_blank" rel="noreferrer">
      <span class="xxai-file-icon" aria-hidden="true">▤</span>
      <span class="xxai-file-copy">
        <strong>{{ block.fileName || '打开文件' }}</strong>
        <small>{{ fileMeta }}</small>
      </span>
      <span class="xxai-file-action" aria-hidden="true">↓</span>
    </a>
    <span v-else-if="loading">正在加载文件...</span>
    <span v-else>{{ block.fallback || '文件暂不可用' }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { AgentClient, MessageContentBlock } from '../../core'

const props = defineProps<{ block: MessageContentBlock; agent?: AgentClient }>()
const block = props.block as MessageContentBlock & { url?: string }
const href = ref('')
const loading = ref(false)
let objectUrl = ''

async function resolveUrl() {
  if (objectUrl) URL.revokeObjectURL(objectUrl)
  objectUrl = ''
  href.value = ''
  const rawUrl = typeof block.url === 'string' ? block.url : ''
  if (/^https?:\/\//.test(rawUrl)) {
    href.value = rawUrl
    return
  }
  if (!rawUrl || !props.agent) return
  loading.value = true
  try {
    objectUrl = await props.agent.loadAsset(rawUrl)
    href.value = objectUrl
  } catch {
    href.value = ''
  } finally {
    loading.value = false
  }
}

const fileMeta = computed(() => [
  block.size ? `${Math.ceil(block.size / 1024)} KB` : '',
  block.mimeType || '文件'
].filter(Boolean).join(' · '))

onMounted(resolveUrl)
watch(() => block.url, resolveUrl)
onBeforeUnmount(() => {
  if (objectUrl) URL.revokeObjectURL(objectUrl)
})
</script>
