<template>
  <div class="xxai-actions-content">
    <button
      v-for="action in actions"
      :key="action.value"
      type="button"
      @click="$emit('action', action.value)"
    >
      {{ action.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { MessageContentBlock } from '../../core'

type Action = { label: string; value: string }
const props = defineProps<{ block: MessageContentBlock }>()
defineEmits<{ action: [value: string] }>()
const data = props.block.props || props.block.metadata || {}
const actions = computed(() => Array.isArray(data.actions) ? data.actions as Action[] : [])
</script>
