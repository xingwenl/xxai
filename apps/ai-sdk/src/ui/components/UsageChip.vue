<template>
  <div v-if="view" class="xxai-usage">
    <button
      type="button"
      class="xxai-usage-chip"
      :aria-expanded="open"
      :title="view.totalText"
      @click="open = !open"
    >
      <svg
        class="xxai-usage-chip-icon"
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
      >
        <ellipse cx="8" cy="3.5" rx="5" ry="2" stroke="currentColor" stroke-width="1.2" />
        <path
          d="M3 3.5v9c0 1.1 2.24 2 5 2s5-.9 5-2v-9"
          stroke="currentColor"
          stroke-width="1.2"
        />
        <path
          d="M3 8c0 1.1 2.24 2 5 2s5-.9 5-2"
          stroke="currentColor"
          stroke-width="1.2"
        />
      </svg>
      <span>{{ view.text }}</span>
    </button>
    <div v-if="open" class="xxai-usage-panel" role="group" :aria-label="view.title">
      <div class="xxai-usage-panel-head">
        <span class="xxai-usage-panel-title">{{ view.title }}</span>
        <span class="xxai-usage-panel-total">{{ view.totalText }}</span>
      </div>
      <dl class="xxai-usage-rows">
        <div v-for="row in view.rows" :key="row.label" class="xxai-usage-row">
          <dt>{{ row.label }}</dt>
          <dd>{{ row.value }}</dd>
        </div>
      </dl>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import type { ModelUsage } from '../../core';
import { usageChipView } from '../usage-view';

const props = defineProps<{
  /** 单条消息的用量；调用方已用 `parseUsage` 解析，非法值直接不传。 */
  usage: ModelUsage | null;
}>();

const open = ref(false);
const view = computed(() => usageChipView(props.usage));
</script>

<style scoped>
.xxai-usage {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  margin-top: 8px;
}

.xxai-usage-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border: var(--agent-glass-border);
  border-radius: 999px;
  background: var(--agent-card);
  color: var(--agent-muted-foreground);
  font-size: 12px;
  line-height: 1.7;
  font-family: inherit;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease;
}

.xxai-usage-chip:hover,
.xxai-usage-chip[aria-expanded='true'] {
  color: var(--agent-foreground);
}

.xxai-usage-chip:focus-visible {
  outline: 2px solid var(--agent-primary, #0ea5e9);
  outline-offset: 2px;
}

.xxai-usage-chip-icon {
  width: 12px;
  height: 12px;
  flex: none;
}

.xxai-usage-panel {
  min-width: 216px;
  max-width: 292px;
  padding: 12px 14px;
  border: var(--agent-glass-border);
  border-radius: 12px;
  background: var(--agent-card);
  box-shadow: var(--agent-shadow-soft);
  animation: xxai-fade-in 0.18s ease;
}

.xxai-usage-panel-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 8px;
  border-bottom: var(--agent-glass-border);
}

.xxai-usage-panel-title {
  color: var(--agent-foreground);
  font-size: 13px;
  font-weight: 600;
}

.xxai-usage-panel-total {
  color: var(--agent-foreground);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.xxai-usage-rows {
  display: grid;
  gap: 6px;
  margin: 8px 0 0;
}

.xxai-usage-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
}

.xxai-usage-row dt {
  color: var(--agent-muted-foreground);
  font-size: 12px;
}

.xxai-usage-row dd {
  margin: 0;
  color: var(--agent-foreground);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  text-align: right;
  word-break: break-all;
}
</style>
