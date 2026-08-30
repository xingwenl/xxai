<template>
  <div class="xxai-custom-content">
    <span>{{ block.component_name   }}</span>
    <component v-if="component" :is="component" v-bind="block.props || {}" />
    <span v-else>{{ block.fallback || `组件 ${block.component_name || block.componentName || 'custom'} 暂不可用` }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { MessageContentBlock } from '../../core'
import { getCustomComponent } from '../registry'

const props = defineProps<{ block: MessageContentBlock }>()
const block = props.block
// 协议字段统一为 component_name（snake_case），componentName 仅兜底存量数据
const component = computed(() => getCustomComponent(block.component_name ?? block.componentName))
</script>
