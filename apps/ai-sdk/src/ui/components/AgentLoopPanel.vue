<template>
  <section v-if="message.loop" class="xxai-agent-loop">
    <button
      class="xxai-loop-summary"
      type="button"
      :aria-expanded="expanded"
      :disabled="!canExpand"
      @click="toggleExpanded"
    >
      <span class="xxai-loop-summary-left">
        <span
          v-for="kind in presentKinds"
          :key="kind"
          class="xxai-summary-dot"
          :class="`kind-${kind}`"
        ></span>
        <strong>{{ summaryLabel }}</strong>
        <span v-if="message.loop?.status === 'running'" class="xxai-loop-summary-dots" aria-label="运行中"><span></span><span></span><span></span></span>
      </span>
      <svg
        v-if="canExpand"
        class="xxai-loop-chevron"
        :class="{ expanded }"
        xmlns="http://www.w3.org/2000/svg"
        width="24"
        height="24"
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
    </button>
    <div v-if="expanded" class="xxai-loop-details">
      <template
        v-for="item in renderSteps"
        :key="item.kind === 'group' ? 'skill-group' : item.step.id"
      >
        <AgentLoopSkillGroup v-if="item.kind === 'group'" :steps="item.steps" />
        <AgentLoopStepCard v-else :step="item.step" />
      </template>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { AgentLoopStep, Message } from '../../core';
import { leadingSkillSteps, loopSummaryLabel } from '../message-presentation';
import AgentLoopSkillGroup from './AgentLoopSkillGroup.vue';
import AgentLoopStepCard from './AgentLoopStepCard.vue';

const props = defineProps<{ message: Message }>();
const expanded = ref(Boolean(props.message.loop?.status === 'running' && props.message.loop.steps.length));
const userCollapsed = ref(false);
const sortedSteps = computed(() =>
  [...(props.message.loop?.steps || [])].sort((a, b) => a.sequence - b.sequence),
);
const skillGroupSteps = computed<AgentLoopStep[]>(() =>
  leadingSkillSteps(sortedSteps.value),
);
type RenderItem =
  | { kind: 'group'; steps: AgentLoopStep[] }
  | { kind: 'step'; step: AgentLoopStep };
const renderSteps = computed<RenderItem[]>(() => {
  const group = skillGroupSteps.value;
  const groupIds = new Set(group.map((step) => step.id));
  const items: RenderItem[] = [];
  let groupRendered = false;
  for (const step of sortedSteps.value) {
    if (groupIds.has(step.id)) {
      if (!groupRendered) {
        items.push({ kind: 'group', steps: group });
        groupRendered = true;
      }
      continue;
    }
    items.push({ kind: 'step', step });
  }
  return items;
});
const canExpand = computed(() => sortedSteps.value.length > 0);
const presentKinds = computed(() => [
  ...new Set(sortedSteps.value.map(kindFor)),
]);
const summaryLabel = computed(() =>
  props.message.loop ? loopSummaryLabel(props.message.loop) : '思考中',
);

watch(
  () => sortedSteps.value.length,
  (count, previousCount) => {
    // 首个真实步骤到达时展示过程；用户收起后，后续步骤更新不再强制展开。
    if (previousCount === 0 && count > 0 && props.message.loop?.status === 'running') {
      expanded.value = true;
    }
  },
);

watch(
  () => props.message.loop?.status,
  (status, previousStatus) => {
    // 运行结束时自动展开，让过程明细按时间顺序保留在消息中。
    if (
      previousStatus === 'running' &&
      (status === 'completed' || status === 'failed' || status === 'cancelled') &&
      sortedSteps.value.length > 0 &&
      !userCollapsed.value
    ) {
      expanded.value = true;
    }
  },
);

function toggleExpanded() {
  if (!canExpand.value) return;
  expanded.value = !expanded.value;
  if (!expanded.value) userCollapsed.value = true;
}

function kindFor(step: AgentLoopStep) {
  if (step.stepType === 'knowledge_retrieval') return 'knowledge';
  if (step.stepType === 'skill_instruction' || step.stepType === 'skill_tool')
    return 'skill';
  if (
    step.stepType === 'builtin_tool' ||
    step.stepType === 'host_tool' ||
    step.stepType === 'mcp_tool'
  )
    return 'tool';
  return 'thinking';
}
</script>

<style scoped>
.xxai-agent-loop {
  margin-top: 2px;
  color: #64748b;
  font-size: 12px;
}
.xxai-loop-summary {
  width: 100%;
  min-height: 38px;
  padding: 8px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  border: 1px solid rgba(255, 255, 255, 0.8);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.78);
  box-shadow:
    0 4px 20px rgba(15, 23, 42, 0.05),
    0 1px 3px rgba(15, 23, 42, 0.03);
  color: #64748b;
  cursor: pointer;
  backdrop-filter: blur(18px) saturate(160%);
}
.xxai-loop-summary:disabled {
  cursor: default;
}
.xxai-loop-summary-left {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}
.xxai-loop-summary-left strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 700;
  line-height: 1.2;
}
.xxai-loop-summary-dots {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  flex: 0 0 auto;
  color: #8b5cf6;
}
.xxai-loop-summary-dots span {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: currentColor;
  animation: xxai-loop-typing-bounce 1.4s infinite ease-in-out both;
}
.xxai-loop-summary-dots span:nth-child(2) { animation-delay: .2s; }
.xxai-loop-summary-dots span:nth-child(3) { animation-delay: .4s; }
.xxai-summary-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 50%;
  box-shadow: 0 0 6px currentColor;
}
.kind-thinking {
  color: #8b5cf6;
  background: #8b5cf6;
}
.kind-tool {
  color: #3b82f6;
  background: #3b82f6;
}
.kind-skill {
  color: #10b981;
  background: #10b981;
}
.kind-knowledge {
  color: #f59e0b;
  background: #f59e0b;
}
.xxai-loop-chevron {
  width: 16px;
  height: 16px;
  display: grid;
  place-items: center;
  flex: 0 0 16px;
  font-size: 18px;
  line-height: 1;
  transition: transform 0.2s ease;
}
.xxai-loop-chevron.expanded {
  transform: rotate(180deg);
}
.xxai-loop-details {
  display: grid;
  gap: 6px;
  padding-top: 6px;
  min-width: 0;
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
  .xxai-loop-summary-dots span {
    animation: none !important;
  }
}
@media (max-width: 480px) {
  .xxai-loop-summary {
    padding: 8px 12px;
  }
  .xxai-loop-summary-left strong {
    font-size: 12px;
  }
}
</style>
