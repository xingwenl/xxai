<template>
  <article class="xxai-chat-message" :class="message.role">
    <div v-if="message.role === 'user'" class="xxai-user-message">
      <MessageContent :blocks="contentBlocks" @action="handleAction" />
    </div>
    <div v-else class="xxai-assistant-message">
      <div class="xxai-assistant-row">
        <div class="xxai-agent-avatar" aria-hidden="true">✦</div>
        <div class="xxai-assistant-content">
          <template v-if="timelineEntries.length">
            <div
              v-for="entry in timelineEntries"
              :key="entry.id"
              class="xxai-timeline-entry"
            >
              <MessageContent
                v-if="entry.kind === 'text'"
                :blocks="[textBlock(entry.text)]"
                @action="handleAction"
              />
              <AgentLoopSkillGroup v-else-if="entry.kind === 'group'" :steps="entry.steps" />
              <AgentLoopStepCard v-else :step="entry.step" />
            </div>
          </template>
          <template v-else>
            <TypingIndicator v-if="pending && !hasRenderableContent && !message.loop" />
            <MessageContent
              v-else-if="hasRenderableContent"
              :blocks="contentBlocks"
              @action="handleAction"
            />
            <AgentLoopPanel :message="message" />
          </template>
        </div>
      </div>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AgentLoopStep, Message, MessageContentBlock } from '../../core'
import AgentLoopPanel from './AgentLoopPanel.vue'
import AgentLoopSkillGroup from './AgentLoopSkillGroup.vue'
import AgentLoopStepCard from './AgentLoopStepCard.vue'
import MessageContent from './MessageContent.vue'
import TypingIndicator from './TypingIndicator.vue'
import { hasRenderableMessageContent, leadingSkillSteps } from '../message-presentation'

const props = defineProps<{
  message: Message
  pending?: boolean
}>()
const emit = defineEmits<{ buttonClick: [value: string] }>()
type TimelineRenderEntry =
  | { id: string; kind: 'text'; text: string }
  | { id: string; kind: 'step'; step: AgentLoopStep }
  | { id: string; kind: 'group'; steps: AgentLoopStep[] }
const contentBlocks = computed<MessageContentBlock[]>(() => props.message.contentBlocks?.length
  ? props.message.contentBlocks
  : [{
      id: `${props.message.id}-text`,
      type: 'markdown',
      text: String((props.message.content as { text?: string }).text || ''),
      status: 'completed'
    }])
const hasRenderableContent = computed(() => hasRenderableMessageContent(contentBlocks.value))

const timelineEntries = computed<TimelineRenderEntry[]>(() => {
  const stepsById = new Map<string, AgentLoopStep>(
    (props.message.loop?.steps || []).map((step) => [step.id, step])
  )
  const groupSteps = leadingSkillSteps(props.message.loop?.steps || [])
  const groupIds = new Set(groupSteps.map((step) => step.id))
  const entries: TimelineRenderEntry[] = []
  let groupRendered = false
  for (const entry of props.message.timeline || []) {
    if (entry.kind === 'text') {
      entries.push({ id: entry.id, kind: 'text', text: entry.text })
      continue
    }
    const step = stepsById.get(entry.stepId)
    if (!step) continue
    if (groupIds.has(step.id)) {
      if (!groupRendered) {
        entries.push({ id: entry.id, kind: 'group', steps: groupSteps })
        groupRendered = true
      }
      continue
    }
    entries.push({ id: entry.id, kind: 'step', step })
  }
  return entries
})

function textBlock(text: string): MessageContentBlock {
  return {
    id: 'timeline-text',
    type: 'markdown',
    text,
    status: props.pending ? 'streaming' : 'completed'
  }
}

function handleAction(value: string) {
  emit('buttonClick', value)
}
</script>

<style scoped>
.xxai-timeline-entry {
  display: grid;
  gap: 6px;
  min-width: 0;
}
.xxai-timeline-entry + .xxai-timeline-entry {
  margin-top: 8px;
}
</style>
