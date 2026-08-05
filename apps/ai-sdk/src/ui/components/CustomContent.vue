<template>
  <div class="xxai-custom-content">
    <component v-if="component" :is="component" v-bind="block.props || {}" />
    <span v-else>{{ block.fallback || `组件 ${block.componentName || 'custom'} 暂不可用` }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { MessageContentBlock } from '../../core'
import { getCustomComponent } from '../registry'

const props = defineProps<{ block: MessageContentBlock }>()
const block = props.block
const component = computed(() => getCustomComponent(block.componentName))
</script>
