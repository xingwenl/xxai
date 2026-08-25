<template>
  <div
    v-if="state"
    class="xxai-quota-ring"
    :title="windowSeconds ? `消息配额：每 ${windowSeconds} 秒窗口重置` : '消息配额'"
  >
    <svg class="xxai-quota-ring-svg" viewBox="0 0 36 36" aria-hidden="true">
      <circle
        class="xxai-quota-ring-track"
        cx="18"
        cy="18"
        r="15.5"
        fill="none"
        stroke-width="3"
      />
      <circle
        class="xxai-quota-ring-value"
        cx="18"
        cy="18"
        r="15.5"
        fill="none"
        stroke-width="3"
        stroke-linecap="round"
        :stroke="state.color"
        :stroke-dasharray="CIRCUMFERENCE"
        :stroke-dashoffset="dashOffset"
        :transform="`rotate(-90 18 18)`"
      />
    </svg>
    <!-- <span class="xxai-quota-ring-text">{{ state.text }}</span> -->
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { quotaRingState } from '../quota-ring'

interface Props {
  current?: number
  limit?: number
  windowSeconds?: number
}

const props = withDefaults(defineProps<Props>(), {
  current: undefined,
  limit: undefined,
  windowSeconds: undefined
})

const CIRCUMFERENCE = 2 * Math.PI * 15.5
const state = computed(() => quotaRingState(props.current, props.limit))
const dashOffset = computed(() =>
  state.value ? CIRCUMFERENCE * (1 - state.value.ratio) : CIRCUMFERENCE
)
</script>
