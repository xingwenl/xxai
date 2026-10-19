<template>
  <div v-if="state" class="xxai-context-ring" :title="title || state.text">
    <svg class="xxai-context-ring-svg" viewBox="0 0 36 36" aria-hidden="true">      <circle
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
    <!-- QuotaRing 里这段文本被注释掉了；上下文占用必须让用户看到具体数字，
         因此这里显式渲染（环只有 20px，文字放在环右侧由外部样式排版）。 -->
    <span class="xxai-context-ring-text">{{ state.text }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ContextRingState } from '../context-ring'

interface Props {
  /** `contextRingState()` 的结果；为 null（窗口未知）时整块不渲染。 */
  state: ContextRingState | null
  /** 悬停提示；缺省直接用占用文本。 */
  title?: string
}

const props = withDefaults(defineProps<Props>(), { title: undefined })

const CIRCUMFERENCE = 2 * Math.PI * 15.5
// ratio 是 0–100 的百分比，换算弧长时先除以 100。
const dashOffset = computed(() =>
  props.state ? CIRCUMFERENCE * (1 - props.state.ratio / 100) : CIRCUMFERENCE
)
</script>
