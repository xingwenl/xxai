<template>
  <section class="xxai-question-card" role="group" aria-live="assertive">
    <div class="xxai-question-card-header">
      <span class="xxai-question-card-mark" aria-hidden="true">?</span>
      <div>
        <p class="xxai-question-card-eyebrow">需要你选择</p>
        <h3>{{ question.question }}</h3>
      </div>
    </div>
    <p v-if="question.description" class="xxai-question-card-description">
      {{ question.description }}
    </p>
    <div class="xxai-question-card-options" role="radiogroup">
      <label
        v-for="option in question.options"
        :key="option.id"
        class="xxai-question-card-option"
      >
        <input
          v-model="selectedOptionId"
          type="radio"
          name="xxai-question-option"
          :value="option.id"
          :disabled="expired || submitting"
        />
        <span>{{ option.label }}</span>
      </label>
    </div>
    <label v-if="question.allowFreeText" class="xxai-question-card-free-text">
      <span>其他（自定义答案）</span>
      <input
        v-model="freeText"
        type="text"
        placeholder="输入你的答案..."
        maxlength="500"
        :disabled="expired || submitting"
      />
    </label>
    <p v-if="expired" class="xxai-question-card-expired">
      问题已超时，未收到你的选择。
    </p>
    <div v-else class="xxai-question-card-actions">
      <button
        type="button"
        class="xxai-question-card-submit"
        :disabled="!canSubmit || submitting"
        @click="submit"
      >
        {{ submitting ? '提交中...' : '提交选择' }}
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import type { AgentClient, AgentQuestion } from '../../core'

const props = defineProps<{
  agent: AgentClient
  question: AgentQuestion
}>()

const selectedOptionId = ref<string | undefined>(undefined)
const freeText = ref('')
const submitting = ref(false)
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | undefined

const expiresAt = computed(() => {
  if (!props.question.expiresAt) return undefined
  const value = Date.parse(props.question.expiresAt)
  return Number.isFinite(value) ? value : undefined
})
const expired = computed(
  () => expiresAt.value !== undefined && expiresAt.value <= now.value,
)
const hasFreeText = computed(
  () => props.question.allowFreeText && freeText.value.trim().length > 0,
)
const canSubmit = computed(
  () =>
    !expired.value &&
    !submitting.value &&
    (selectedOptionId.value !== undefined || hasFreeText.value),
)

if (expiresAt.value !== undefined) {
  timer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
}

function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  props.agent.answerQuestion(props.question.questionId, {
    selectedOptionId: selectedOptionId.value,
    freeText: hasFreeText.value ? freeText.value.trim() : undefined,
  })
}

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.xxai-question-card {
  position: absolute;
  right: 14px;
  bottom: 72px;
  left: 14px;
  z-index: 4;
  max-height: min(340px, calc(100% - 148px));
  overflow-y: auto;
  padding: 14px;
  border: 1px solid #A5B4FC;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.96);
  color: var(--agent-foreground);
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.18);
}

.xxai-question-card-header {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.xxai-question-card-mark {
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #EEF2FF;
  color: #4338CA;
  font-size: 14px;
  font-weight: 700;
}

.xxai-question-card-eyebrow,
.xxai-question-card-header h3,
.xxai-question-card-description,
.xxai-question-card-expired {
  margin: 0;
}

.xxai-question-card-eyebrow {
  color: #4338CA;
  font-size: 12px;
  font-weight: 600;
}

.xxai-question-card-header h3 {
  max-width: 100%;
  overflow-wrap: anywhere;
  font-size: 15px;
  line-height: 1.4;
}

.xxai-question-card-description {
  margin-top: 10px;
  color: #475569;
  font-size: 13px;
  line-height: 1.5;
}

.xxai-question-card-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}

.xxai-question-card-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid #E2E8F0;
  border-radius: 6px;
  background: #F8FAFC;
  color: #334155;
  font-size: 13px;
  cursor: pointer;
}

.xxai-question-card-option input {
  accent-color: #4338CA;
}

.xxai-question-card-free-text {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 10px;
  color: #475569;
  font-size: 12px;
}

.xxai-question-card-free-text input {
  min-height: 36px;
  padding: 0 10px;
  border: 1px solid #CBD5E1;
  border-radius: 6px;
  background: #FFFFFF;
  color: #0F172A;
  font: inherit;
  font-size: 13px;
}

.xxai-question-card-free-text input:focus {
  border-color: #4338CA;
  outline: none;
}

.xxai-question-card-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.xxai-question-card-submit {
  min-height: 36px;
  padding: 0 16px;
  border: 1px solid #4338CA;
  border-radius: 6px;
  background: #4338CA;
  color: #FFFFFF;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.xxai-question-card-submit:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.xxai-question-card-expired {
  margin-top: 12px;
  color: #B91C1C;
  font-size: 13px;
}
</style>
