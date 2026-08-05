<template>
  <div class="xxai-file-content">
    <a v-if="url" :href="url" target="_blank" rel="noreferrer">
      <span class="xxai-file-icon" aria-hidden="true">▤</span>
      <span class="xxai-file-copy">
        <strong>{{ block.fileName || '打开文件' }}</strong>
        <small>{{ fileMeta }}</small>
      </span>
      <span class="xxai-file-action" aria-hidden="true">↓</span>
    </a>
    <span v-else>{{ block.fallback || '文件暂不可用' }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { MessageContentBlock } from '../../core'

const props = defineProps<{ block: MessageContentBlock }>()
const block = props.block as MessageContentBlock & { url?: string }
const url = typeof block.url === 'string' && /^https?:\/\//.test(block.url) ? block.url : ''
const fileMeta = computed(() => [
  block.size ? `${Math.ceil(block.size / 1024)} KB` : '',
  block.mimeType || '文件'
].filter(Boolean).join(' · '))
</script>
