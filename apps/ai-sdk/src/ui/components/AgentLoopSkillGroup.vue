<template>
  <details
    class="xxai-loop-skill-group"
    :class="`is-${groupStatus}`"
    :open="open"
    @toggle="onToggle"
  >
    <summary class="xxai-loop-skill-group-header">
      <span class="xxai-loop-icon" aria-hidden="true">✦</span>
      <strong>调用技能 · {{ steps.length }} 个</strong>
      <span v-if="groupStatus === 'running'" class="xxai-loop-count">
        <span class="xxai-loop-typing-dots" aria-label="执行中"><span></span><span></span><span></span></span>
      </span>
      <span v-else class="xxai-loop-count">{{ groupStatusText }}</span>
      <svg
        class="xxai-loop-chevron"
        :class="{ expanded: open }"
        xmlns="http://www.w3.org/2000/svg"
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d="m6 9 6 6 6-6"></path>
      </svg>
    </summary>
    <ul class="xxai-loop-skill-list">
      <li v-for="step in steps" :key="step.id" class="xxai-loop-skill-item">
        <span class="xxai-loop-badge">{{ skillNameOf(step) }}</span>
        <span v-if="step.skillVersion" class="xxai-loop-version">v{{ step.skillVersion }}</span>
        <span class="xxai-loop-skill-status" :class="`state-${step.status}`">
          {{ statusIcon(step.status) }}
        </span>
        <span v-if="detailOf(step)" class="xxai-loop-skill-detail">{{ detailOf(step) }}</span>
      </li>
    </ul>
  </details>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import type { AgentLoopStep, AgentLoopStepStatus } from '../../core';
import { truncateText } from '../message-presentation';

const props = defineProps<{ steps: AgentLoopStep[] }>();
const open = ref(true);

const groupStatus = computed<AgentLoopStepStatus>(() => {
  const statuses = props.steps.map((step) => step.status);
  if (statuses.includes('running') || statuses.includes('queued')) return 'running';
  if (statuses.includes('waiting_confirmation')) return 'waiting_confirmation';
  if (statuses.includes('failed') || statuses.includes('cancelled')) return 'failed';
  return 'succeeded';
});
const groupStatusText = computed(() => ({
  running: '执行中',
  succeeded: '完成',
  failed: '失败',
  cancelled: '取消',
  waiting_confirmation: '待确认',
  queued: '排队',
} as Record<AgentLoopStepStatus, string>)[groupStatus.value]);

function onToggle(event: Event) {
  open.value = (event.target as HTMLDetailsElement).open;
}

function skillNameOf(step: AgentLoopStep): string {
  return step.skillName || step.title.replace(/^(?:调用工具|应用技能)[:：]?\s*/, '');
}

function detailOf(step: AgentLoopStep): string {
  return truncateText(step.outputSummary?.trim() || '', 120);
}

function statusIcon(status: AgentLoopStepStatus): string {
  return status === 'failed' || status === 'cancelled'
    ? '!'
    : status === 'waiting_confirmation'
      ? '?'
      : status === 'running' || status === 'queued'
        ? '…'
        : '✓';
}
</script>

<style scoped>
.xxai-loop-skill-group {
  padding: 10px 12px;
  border: 1px solid #a7f3d0;
  border-left: 3px solid #10b981;
  border-radius: 12px;
  background: #ecfdf5;
  color: #047857;
  box-shadow:
    0 4px 20px rgba(15, 23, 42, 0.05),
    0 1px 3px rgba(15, 23, 42, 0.03);
  backdrop-filter: blur(18px) saturate(160%);
  font-size: 12px;
}
.xxai-loop-skill-group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 18px;
  list-style: none;
  cursor: pointer;
  user-select: none;
}
.xxai-loop-skill-group-header::-webkit-details-marker {
  display: none;
}
.xxai-loop-icon {
  width: 16px;
  font-size: 16px;
  text-align: center;
}
.xxai-loop-count {
  margin-left: auto;
  font-weight: 500;
}
.xxai-loop-chevron {
  flex: 0 0 16px;
  transition: transform 0.2s ease;
}
.xxai-loop-chevron.expanded {
  transform: rotate(180deg);
}
.xxai-loop-skill-list {
  display: grid;
  gap: 4px;
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
}
.xxai-loop-skill-item {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 6px 8px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.5);
  line-height: 1.4;
}
.xxai-loop-badge {
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.55);
  font-weight: 500;
}
.xxai-loop-version {
  opacity: 0.68;
}
.xxai-loop-skill-status {
  color: #10b981;
  font-size: 14px;
  line-height: 1;
}
.xxai-loop-skill-status.state-failed,
.xxai-loop-skill-status.state-cancelled {
  color: #dc2626;
}
.xxai-loop-skill-status.state-waiting_confirmation {
  color: #f59e0b;
}
.xxai-loop-skill-detail {
  min-width: 0;
  flex: 1 1 100%;
  opacity: 0.8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.xxai-loop-typing-dots {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 0;
}
.xxai-loop-typing-dots span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  animation: xxai-loop-typing-bounce 1.4s infinite ease-in-out both;
}
.xxai-loop-typing-dots span:nth-child(1) {
  animation-delay: 0s;
}
.xxai-loop-typing-dots span:nth-child(2) {
  animation-delay: 0.2s;
}
.xxai-loop-typing-dots span:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes xxai-loop-typing-bounce {
  0%,
  60%,
  100% {
    transform: translateY(0);
    opacity: 0.4;
  }
  30% {
    transform: translateY(-5px);
    opacity: 1;
  }
}
@media (prefers-reduced-motion: reduce) {
  .xxai-loop-typing-dots span {
    animation: none !important;
  }
}
</style>
