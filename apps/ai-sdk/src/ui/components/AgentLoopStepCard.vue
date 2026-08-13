<template>
  <article class="xxai-loop-card" :class="cardClass">
    <header class="xxai-loop-card-header">
      <span class="xxai-loop-icon" aria-hidden="true">{{ iconFor }}</span>
      <strong>{{ label }}</strong>
      <span v-if="isThinking" class="xxai-loop-count">
        <span v-if="step.status === 'running'" class="xxai-loop-typing-dots" aria-label="思考中"><span></span><span></span><span></span></span>
        <template v-else>{{ stepStatusText(step.status) }}</template>
      </span>
      <span v-else class="xxai-loop-state" :class="`state-${step.status}`">
        <span v-if="step.status === 'running'" class="xxai-loop-typing-dots" aria-label="执行中"><span></span><span></span><span></span></span>
        <template v-else>{{ stateIcon(step.status) }}</template>
      </span>
    </header>

    <template v-if="isThinking">
      <p v-if="!step.thinkingText" class="xxai-loop-thinking-text">{{ thinkingPlaceholder }}</p>
      <details
        v-else
        class="xxai-loop-collapse"
        :open="thinkingOpen"
        @toggle="onThinkingToggle"
      >
        <summary>思考过程（{{ step.thinkingText.length }} 字）</summary>
        <div class="xxai-loop-long-text">{{ step.thinkingText }}</div>
      </details>
    </template>

    <template v-else-if="isTool">
      <div class="xxai-loop-detail-line">
        <span class="xxai-loop-badge">{{ toolName }}</span>
        <span>{{ toolStatusText(step) }}</span>
        <span v-if="step.skillVersion" class="xxai-loop-version">v{{ step.skillVersion }}</span>
      </div>
      <details v-if="inputSummary" class="xxai-loop-collapse" open>
        <summary>发送的参数</summary>
        <pre class="xxai-loop-code">{{ inputSummary }}</pre>
      </details>
      <details v-if="outputDetail" class="xxai-loop-collapse" open>
        <summary>返回的结果</summary>
        <pre class="xxai-loop-code">{{ outputDetail }}</pre>
      </details>
    </template>

    <div v-else-if="step.stepType === 'skill_instruction'" class="xxai-loop-detail-line">
      <span class="xxai-loop-badge">{{ skillName }}</span>
      <span>{{ step.outputSummary || '正在加载技能...' }}</span>
      <span v-if="step.skillVersion" class="xxai-loop-version">v{{ step.skillVersion }}</span>
    </div>

    <div v-else-if="step.stepType === 'knowledge_retrieval'" class="xxai-loop-references">
      <div v-for="(citation, index) in step.citationRefs || []" :key="index" class="xxai-loop-reference">
        <span class="xxai-reference-icon" aria-hidden="true">▤</span>
        <span class="xxai-reference-body">
          <strong>{{ citationTitle(citation, index) }}</strong>
          <small v-if="knowledgeBaseName" class="xxai-reference-kb">{{ knowledgeBaseName }}</small>
          <small v-if="passage" class="xxai-reference-passage">{{ passage }}</small>
          <small v-if="!passage" class="xxai-reference-source">{{ citationSourceText(citation) }}</small>
        </span>
      </div>
      <span v-if="!step.citationRefs?.length" class="xxai-loop-empty">{{ step.outputSummary || '未命中知识库引用' }}</span>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import type { AgentLoopStep, AgentLoopStepStatus, KnowledgeCitation } from '../../core';
import {
  THINKING_PLACEHOLDER,
  toolInputSummary,
  toolOutputSummary,
  toolOutputDetail,
  toolStatusText,
  citationKnowledgeBaseName,
  citationPassage,
  citationTitle,
  citationSourceText,
  truncateText,
} from '../message-presentation';

const props = defineProps<{ step: AgentLoopStep }>();

const kind = computed(() => {
  const step = props.step;
  if (step.stepType === 'knowledge_retrieval') return 'knowledge';
  if (step.stepType === 'skill_instruction' || step.stepType === 'skill_tool') return 'skill';
  if (
    step.stepType === 'builtin_tool' ||
    step.stepType === 'host_tool' ||
    step.stepType === 'mcp_tool'
  ) return 'tool';
  return 'thinking';
});
const cardClass = computed(() => `kind-${kind.value} is-${props.step.status}`);
const label = computed(() => ({
  thinking: props.step.status === 'running' ? '思考中' : '生成回答',
  tool: '调用工具',
  skill: '调用技能',
  knowledge: '知识库引用',
} as Record<string, string>)[kind.value]);
const iconFor = computed(() => ({ thinking: '✣', tool: '▣', skill: '✦', knowledge: '▤' } as Record<string, string>)[kind.value]);
const isThinking = computed(() => props.step.stepType === 'model_generation' || props.step.stepType === 'thinking');
const isTool = computed(() => (
  props.step.stepType === 'builtin_tool' ||
  props.step.stepType === 'host_tool' ||
  props.step.stepType === 'mcp_tool' ||
  props.step.stepType === 'skill_tool'
));
const toolName = computed(() => props.step.skillName || props.step.toolName || props.step.title.replace(/^调用工具：/, ''));
const skillName = computed(() => props.step.skillName || props.step.title.replace(/^应用技能：/, ''));
const thinkingPlaceholder = computed(() => THINKING_PLACEHOLDER);
const inputSummary = computed(() => toolInputSummary(props.step));
const outputDetail = computed(() => toolOutputDetail(props.step));
const thinkingOpen = ref(props.step.status === 'running');

function onThinkingToggle(event: Event) {
  thinkingOpen.value = (event.target as HTMLDetailsElement).open;
}

function stateIcon(status: AgentLoopStepStatus) {
  return status === 'failed'
    ? '!'
    : status === 'waiting_confirmation'
      ? '?'
      : '✓';
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

function knowledgeBaseName(citation: KnowledgeCitation): string {
  return citationKnowledgeBaseName(citation);
}

function passage(citation: KnowledgeCitation): string {
  return truncateText(citationPassage(citation), 200);
}
</script>

<style scoped>
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
.state-failed {
  color: #dc2626;
}
.state-waiting_confirmation {
  color: #f59e0b;
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
.xxai-loop-thinking-text {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
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
.xxai-loop-collapse {
  margin-top: 6px;
  font-size: 12px;
}
.xxai-loop-collapse summary {
  cursor: pointer;
  opacity: 0.8;
  user-select: none;
}
.xxai-loop-code {
  margin: 6px 0 0;
  padding: 8px;
  max-height: 220px;
  overflow: auto;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.6);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
.xxai-loop-long-text {
  margin-top: 6px;
  max-height: 260px;
  overflow: auto;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
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
.xxai-reference-body {
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
.xxai-reference-kb {
  margin-top: 2px;
  color: #b45309;
  font-weight: 600;
  font-size: 11px;
}
.xxai-reference-passage {
  margin-top: 2px;
  font-size: 11px;
  opacity: 0.85;
  line-height: 1.45;
  white-space: normal;
}
.xxai-reference-source {
  margin-top: 2px;
  font-size: 11px;
  opacity: 0.72;
  white-space: nowrap;
  max-width: 100%;
}
.xxai-loop-empty {
  opacity: 0.7;
  font-size: 12px;
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
</style>
