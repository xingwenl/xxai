<template>
  <div class="xxai-image-content">
    <span v-if="loading">正在加载图片...</span>
    <img v-else-if="url" :src="url" :alt="block.alt || ''" @error="handleImageError" />
    <span v-else>{{ block.fallback || '图片暂不可用' }}</span>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { AgentClient, MessageContentBlock } from '../../core'

const props = defineProps<{ block: MessageContentBlock; agent?: AgentClient }>()
const block = props.block as MessageContentBlock & { url?: string; previewUrl?: string; asset_id?: string; assetId?: string }
const url = ref('')
const loading = ref(false)
let objectUrl = ''

async function resolveUrl() {
  if (objectUrl) URL.revokeObjectURL(objectUrl)
  objectUrl = ''
  url.value = ''
  const rawUrl = typeof block.url === 'string' ? block.url : ''
  const previewUrl = typeof block.previewUrl === 'string' ? block.previewUrl : ''
  const assetId = block.assetId || block.asset_id
  if (previewUrl && !loading.value) {
    // url.value = previewUrl
    // return
  }
  if (/^https?:\/\//.test(rawUrl)) {
    url.value = rawUrl
    return
  }
  console.log('rawUrl', rawUrl)
  if (!rawUrl || !assetId || !props.agent) return
  loading.value = true
  try {
    objectUrl = await props.agent.loadAsset(rawUrl)
    url.value = objectUrl
  } catch(err) {
    console.log(err)
    url.value = ''
  } finally {
    loading.value = false
  }
}

async function handleImageError() {
  if (url.value === block.previewUrl) {
    loading.value = true
    url.value = ''
    try {
      objectUrl = await props.agent?.loadAsset(block.url || '') || ''
      url.value = objectUrl
    } catch {
      url.value = ''
    } finally {
      loading.value = false
    }
  }
}

onMounted(resolveUrl)
watch(() => [block.url, block.previewUrl, block.assetId, block.asset_id], resolveUrl)
onBeforeUnmount(() => {
  if (objectUrl) URL.revokeObjectURL(objectUrl)
})
</script>
