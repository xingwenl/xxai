<template>
  <section v-if="loop" class="xxai-agent-loop">
    <button
      class="xxai-loop-summary"
      type="button"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      <span class="xxai-loop-summary-left">
        <span
          v-for="kind in presentKinds"
          :key="kind"
          class="xxai-summary-dot"
          :class="`kind-${kind}`"
        ></span>
        <strong>{{ summaryLabel }}</strong>
        <span v-if="loop?.status === 'running'" class="xxai-loop-summary-dots" aria-label="运行中"><span></span><span></span><span></span></span>
      </span>
      <!-- <span class="xxai-loop-chevron" :class="{ expanded }" aria-hidden="true">⌄</span> -->
      <svg
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
        data-lucide="chevron-down"
        aria-hidden="true"
        >
        <!-- class="lucide lucide-chevron-down process-chevron" -->
        <path d="m6 9 6 6 6-6"></path>
      </svg>
    </button>
    <div v-if="expanded" class="xxai-loop-details">
      <article
        v-for="step in sortedSteps"
        :key="step.id"
        class="xxai-loop-card"
        :class="cardClass(step)"
      >
        <header class="xxai-loop-card-header">
          <span class="xxai-loop-icon" aria-hidden="true">{{
            iconFor(step)
          }}</span>
          <strong>{{ labelFor(step) }}</strong>
          <span
            v-if="step.stepType === 'model_generation'"
            class="xxai-loop-count"
          >
            <span
              v-if="step.status === 'running'"
              class="xxai-loop-typing-dots"
              aria-label="思考中"
              ><span></span><span></span><span></span
            ></span>
            <template v-else>{{ stepStatusText(step.status) }}</template>
          </span>
          <span v-else class="xxai-loop-state" :class="`state-${step.status}`">
            <span
              v-if="step.status === 'running'"
              class="xxai-loop-typing-dots"
              aria-label="执行中"
              ><span></span><span></span><span></span
            ></span>
            <template v-else>{{ stateIcon(step.status) }}</template>
          </span>
        </header>
        <p
          v-if="
            step.stepType === 'model_generation' || step.stepType === 'thinking'
          "
          class="xxai-loop-thinking-text"
        >
          {{ step.outputSummary || '正在理解你的问题并组织回答...' }}
        </p>
        <div v-else-if="isTool(step)" class="xxai-loop-detail-line">
          <span class="xxai-loop-badge">{{
            step.skillName ||
            step.toolName ||
            step.title.replace(/^调用工具：/, '')
          }}</span>
          <span>{{ step.outputSummary || '正在执行...' }}</span>
          <span v-if="step.skillVersion" class="xxai-loop-version"
            >v{{ step.skillVersion }}</span
          >
        </div>
        <div
          v-else-if="step.stepType === 'skill_instruction'"
          class="xxai-loop-detail-line"
        >
          <span class="xxai-loop-badge">{{
            step.skillName || step.title.replace(/^应用技能：/, '')
          }}</span>
          <span>{{ step.outputSummary || '正在加载技能...' }}</span>
          <span v-if="step.skillVersion" class="xxai-loop-version"
            >v{{ step.skillVersion }}</span
          >
        </div>
        <div
          v-else-if="step.stepType === 'knowledge_retrieval'"
          class="xxai-loop-references"
        >
          <div
            v-for="(citation, index) in step.citationRefs || []"
            :key="index"
            class="xxai-loop-reference"
          >
            <span class="xxai-reference-icon" aria-hidden="true">▤</span>
            <span
              ><strong>{{ citationTitle(citation, index) }}</strong
              ><small>{{ citationSource(citation) }}</small></span
            >
          </div>
          <span v-if="!step.citationRefs?.length" class="xxai-loop-empty">{{
            step.outputSummary || '未命中知识库引用'
          }}</span>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type {
  AgentLoopRun,
  AgentLoopStep,
  AgentLoopStepStatus,
} from '../../core';

const props = defineProps<{ loop?: AgentLoopRun }>();
const loop = computed(() => props.loop);
const expanded = ref(loop.value?.status === 'running');
const sortedSteps = computed(() =>
  [...(loop.value?.steps || [])].sort((a, b) => a.sequence - b.sequence),
);
watch(
  () => loop.value?.status,
  (status) => {
    if (status === 'running') expanded.value = true;
  },
);
const presentKinds = computed(() => [
  ...new Set(sortedSteps.value.map(kindFor)),
]);
const summaryLabel = computed(() =>
  loop.value?.status === 'running'
    ? '思考中 · ' + presentKinds.value.map(kindLabel).join(' · ')
    : '已思考 · ' + presentKinds.value.map(kindLabel).join(' · '),
);
function kindFor(step: AgentLoopStep) {
  if (step.stepType === 'knowledge_retrieval') return 'knowledge';
  if (step.stepType === 'skill_instruction' || step.stepType === 'skill_tool')
    return 'skill';
  if (step.stepType === 'host_tool' || step.stepType === 'mcp_tool')
    return 'tool';
  return 'thinking';
}
function kindLabel(kind: string) {
  return (
    {
      thinking: '已思考',
      tool: '调用工具',
      skill: '调用技能',
      knowledge: '引用知识库',
    } as Record<string, string>
  )[kind];
}
function cardClass(step: AgentLoopStep) {
  return `kind-${kindFor(step)} is-${step.status}`;
}
function labelFor(step: AgentLoopStep) {
  return (
    {
      thinking: step.status === 'running' ? '思考中' : '生成回答',
      tool: '调用工具',
      skill: '调用技能',
      knowledge: '知识库引用',
    } as Record<string, string>
  )[kindFor(step)];
}
function iconFor(step: AgentLoopStep) {
  return (
    { thinking: '✣', tool: '▣', skill: '✦', knowledge: '▤' } as Record<
      string,
      string
    >
  )[kindFor(step)];
}
function isTool(step: AgentLoopStep) {
  return (
    step.stepType === 'host_tool' ||
    step.stepType === 'mcp_tool' ||
    step.stepType === 'skill_tool'
  );
}
function stateIcon(status: AgentLoopStepStatus) {
  return status === 'failed'
    ? '!'
    : status === 'waiting_confirmation'
      ? '?'
      : '✓';
}
function citationTitle(citation: unknown, index: number) {
  const item = citation as Record<string, unknown>;
  return String(item.title || `来源 ${index + 1}`);
}
function citationSource(citation: unknown) {
  const item = citation as Record<string, unknown>;
  return String(
    item.source || item.sourceUrl || item.text || '知识库引用',
  ).slice(0, 100);
}
function stepStatusText(status: AgentLoopStepStatus) {
  return {
    queued: '排队',
    running: '处理中',
    succeeded: '完成',
    failed: '失败',
    cancelled: '取消',
    waiting_confirmation: '待确认',
  }[status];
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
  /* transform: translateY(-1px); */
  transition: transform 0.2s ease;
}
.xxai-loop-chevron.expanded {
  transform: rotate(180deg);
}
.xxai-loop-details {
  display: grid;
  gap: 6px;
  padding-top: 6px;
}
.xxai-loop-card {
  padding: 10px 12px;
  border: 1px solid;
  border-left-width: 3px;
  border-radius: 12px;
  box-shadow:
    0 4px 20px rgba(15, 23, 42, 0.05),
    0 1px 3px rgba(15, 23, 42, 0.03);
  backdrop-filter: blur(18px) saturate(160%);
}
.xxai-loop-card.kind-thinking {
  color: #6d28d9;
  background: #f5f3ff;
  border-color: #ddd6fe;
  border-left-color: #8b5cf6;
}
.xxai-loop-card.kind-tool {
  color: #1d4ed8;
  background: #eff6ff;
  border-color: #bfdbfe;
  border-left-color: #3b82f6;
}
.xxai-loop-card.kind-skill {
  color: #047857;
  background: #ecfdf5;
  border-color: #a7f3d0;
  border-left-color: #10b981;
}
.xxai-loop-card.kind-knowledge {
  color: #b45309;
  background: #fffbeb;
  border-color: #fde68a;
  border-left-color: #f59e0b;
}
.xxai-loop-card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 18px;
  margin-bottom: 4px;
  font-size: 12px;
}
.xxai-loop-icon {
  width: 16px;
  font-size: 16px;
  text-align: center;
}
.xxai-loop-count,
.xxai-loop-state {
  margin-left: auto;
  font-size: 12px;
  font-weight: 500;
}
.xxai-loop-state {
  display: inline-flex;
  align-items: center;
  color: #10b981;
  font-size: 16px;
  line-height: 1;
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
.state-failed {
  color: #dc2626;
}
.state-waiting_confirmation {
  color: #f59e0b;
}
.xxai-loop-thinking-text {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
}
.xxai-loop-detail-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
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
  font-size: 12px;
}
.xxai-loop-references {
  display: grid;
  gap: 4px;
  margin-top: 2px;
}
.xxai-loop-reference {
  display: flex;
  gap: 6px;
  align-items: flex-start;
  min-width: 0;
  padding: 6px 8px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.5);
}
.xxai-reference-icon {
  font-size: 18px;
}
.xxai-loop-reference > span:last-child {
  min-width: 0;
}
.xxai-loop-reference strong,
.xxai-loop-reference small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
}
.xxai-loop-reference strong {
  font-size: 13px;
}
.xxai-loop-reference small {
  margin-top: 2px;
  font-size: 11px;
  opacity: 0.72;
  white-space: nowrap;
  max-width: 100%;
}
.xxai-loop-empty {
  opacity: 0.7;
}
.is-running .xxai-loop-icon {
  animation: xxai-loop-pulse 1.2s ease-in-out infinite;
}
@keyframes xxai-loop-pulse {
  50% {
    opacity: 0.35;
    transform: scale(0.82);
  }
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
@media (max-width: 480px) {
  .xxai-loop-summary {
    padding: 8px 12px;
  }
  .xxai-loop-summary-left strong {
    font-size: 12px;
  }
}
</style>
