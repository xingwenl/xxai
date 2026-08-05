<template>
  <div class="xxai-image-content">
    <img v-if="url" :src="url" :alt="block.alt || ''" />
    <span v-else>{{ block.fallback || '图片暂不可用' }}</span>
  </div>
</template>

<script setup lang="ts">
import type { MessageContentBlock } from '../../core'

const props = defineProps<{ block: MessageContentBlock }>()
const block = props.block as MessageContentBlock & { url?: string }
const url = typeof block.url === 'string' && /^https?:\/\//.test(block.url) ? block.url : ''
</script>
