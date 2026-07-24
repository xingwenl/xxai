<template>
  <button
    class="xxai-float-btn"
    :class="{ left: position === 'left' }"
    @click="handleClick"
  >
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path
        d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"
      />
    </svg>
  </button>
</template>

<script setup lang="ts">
import type { UIOptions } from '../../core'

interface Props {
  position?: UIOptions['position']
}

const { position = 'right' } = defineProps<Props>();

const emit = defineEmits<{
  click: []
}>()

function handleClick() {
  emit('click')
}
</script>
