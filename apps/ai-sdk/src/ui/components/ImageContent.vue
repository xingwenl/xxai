<template>
  <div class="xxai-image-content">
    <span v-if="loading">正在加载图片...</span>
    <img v-else-if="url" :src="url" :alt="block.alt || ''" />
    <span v-else>{{ block.fallback || '图片暂不可用' }}</span>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { AgentClient, MessageContentBlock } from '../../core'

const props = defineProps<{ block: MessageContentBlock; agent?: AgentClient }>()
const block = props.block as MessageContentBlock & { url?: string; asset_id?: string; assetId?: string }
const url = ref('')
const loading = ref(false)
let objectUrl = ''

async function resolveUrl() {
  if (objectUrl) URL.revokeObjectURL(objectUrl)
  objectUrl = ''
  url.value = ''
  const rawUrl = typeof block.url === 'string' ? block.url : ''
  const assetId = block.assetId || block.asset_id
  if (/^https?:\/\//.test(rawUrl)) {
    url.value = rawUrl
    return
  }
  if (!rawUrl || !assetId || !props.agent) return
  loading.value = true
  try {
    objectUrl = await props.agent.loadAsset(rawUrl)
    url.value = objectUrl
  } catch {
    url.value = ''
  } finally {
    loading.value = false
  }
}

onMounted(resolveUrl)
watch(() => [block.url, block.assetId, block.asset_id], resolveUrl)
onBeforeUnmount(() => {
  if (objectUrl) URL.revokeObjectURL(objectUrl)
})
</script>
