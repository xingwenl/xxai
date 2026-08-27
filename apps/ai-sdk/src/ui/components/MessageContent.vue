<template>
  <div class="xxai-message-content-blocks" v-if="blocks && blocks.length > 0">
    <template v-for="block in blocks" :key="block.id">
      <MarkdownContent v-if="block.type === 'markdown' || block.type === 'text'" :text="block.text" :agent="agent" />
      <ImageContent v-else-if="block.type === 'image'" :block="block" :agent="agent" />
      <FileContent v-else-if="block.type === 'file'" :block="block" :agent="agent" />
      <TableContent v-else-if="block.type === 'table' || block.type === 'chart'" :block="block" />
      <ActionsContent v-else-if="block.type === 'actions'" :block="block" @action="handleAction" />
      <CustomContent v-else-if="block.type === 'custom'" :block="block" />
      <div v-else class="xxai-content-error">{{ block.text || block.fallback || '内容加载失败' }}</div>
    </template>
  </div>
</template>

<script setup lang="ts">
import type { AgentClient, MessageContentBlock } from '../../core'
import ActionsContent from './ActionsContent.vue'
import CustomContent from './CustomContent.vue'
import FileContent from './FileContent.vue'
import ImageContent from './ImageContent.vue'
import MarkdownContent from './MarkdownContent.vue'
import TableContent from './TableContent.vue'

const props = defineProps<{ blocks: MessageContentBlock[]; agent?: AgentClient }>()
const agent = props.agent
const emit = defineEmits<{ action: [value: string] }>()

function handleAction(value: string) {
  emit('action', value)
}
</script>
