<template>
  <div class="xxai-history-root xxai-history-list">
    <div v-if="loading && items.length === 0" class="xxai-history-hint xxai-history-hint--loading">
      {{ loadingText }}
    </div>

    <div v-else-if="error" class="xxai-history-hint xxai-history-hint--error">
      {{ error }}
    </div>

    <div v-else-if="items.length === 0" class="xxai-history-hint xxai-history-hint--empty">
      {{ emptyText }}
    </div>

    <template v-else>
      <ul class="xxai-history-items">
        <li v-for="item in items" :key="item.id">
          <div
            class="xxai-history-item"
            role="button"
            tabindex="0"
            :title="displayTitle(item)"
            @click="emit('select', item)"
            @keydown.enter.prevent="emit('select', item)"
            @keydown.space.prevent="emit('select', item)"
          >
            <div class="xxai-history-item-head">
              <span class="xxai-history-item-title">{{ displayTitle(item) }}</span>
              <span
                v-if="item.status !== 'active'"
                class="xxai-history-item-status"
                :class="`is-${item.status}`"
              >{{ item.status }}</span>
            </div>

            <div v-if="item.last_message_preview" class="xxai-history-item-preview">
              {{ item.last_message_preview }}
            </div>

            <div class="xxai-history-item-meta">
              <span class="xxai-history-item-count">{{ item.message_count }} 条消息</span>
              <span v-if="item.agent_name" class="xxai-history-item-agent">{{ item.agent_name }}</span>
              <span class="xxai-history-item-time">{{ formatTime(item.last_message_at ?? item.created_at) }}</span>
            </div>
          </div>
        </li>
      </ul>

      <div class="xxai-history-pager">
        <button
          class="xxai-history-page-btn"
          type="button"
          :disabled="loading || !canPrev"
          @click="goToPage(page - 1)"
        >上一页</button>
        <span class="xxai-history-page-label">{{ page }} / {{ totalPages }}</span>
        <button
          class="xxai-history-page-btn"
          type="button"
          :disabled="loading || !canNext"
          @click="goToPage(page + 1)"
        >下一页</button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type {
  ConversationHistorySource,
  ConversationListParams,
  ConversationSummaryPayload
} from './types'

const props = withDefaults(
  defineProps<{
    source: ConversationHistorySource
    params?: ConversationListParams
    emptyText?: string
    loadingText?: string
  }>(),
  {
    params: undefined,
    emptyText: '暂无会话',
    loadingText: '加载中…'
  }
)

const emit = defineEmits<{
  select: [conversation: ConversationSummaryPayload]
}>()

const items = ref<ConversationSummaryPayload[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const error = ref('')

/** 页大小：`params.page_size` 优先，缺省 20。 */
const pageSize = computed(() => props.params?.page_size ?? 20)
/** 总页数；`total` 为 0 时保底 1 页，避免显示「1 / 0」。 */
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / (pageSize.value || 1))))
const canPrev = computed(() => page.value > 1)
const canNext = computed(() => page.value * pageSize.value < total.value)

function displayTitle(item: ConversationSummaryPayload): string {
  return item.title || '（未命名会话）'
}

/** 时间展示：非法/缺失日期降级为空串，不允许渲染出 Invalid Date。 */
function formatTime(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString()
}

/**
 * 拉取一页。所有 await 都包在 try/catch 里，错误只落地为错误文案，
 * 不产生未捕获的 promise rejection。
 *
 * 用自增的 `requestSeq` 丢弃过期响应：params 快速变化时先发的请求可能后到，
 * 直接写入会让列表与当前筛选条件不一致。
 */
let requestSeq = 0
async function load(): Promise<void> {
  const seq = ++requestSeq
  loading.value = true
  error.value = ''
  try {
    const payload = await props.source.listConversations({
      ...props.params,
      page: page.value,
      page_size: pageSize.value
    })
    if (seq !== requestSeq) return
    items.value = Array.isArray(payload?.items) ? payload.items : []
    total.value = Number(payload?.total) || 0
  } catch (err) {
    if (seq !== requestSeq) return
    items.value = []
    total.value = 0
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

function goToPage(next: number): void {
  if (next < 1 || next > totalPages.value || next === page.value) return
  page.value = next
  void load()
}

/**
 * `params` 变化即重新拉取：`params.page` 显式变化时同步页码，其余变化
 * （筛选条件等）一律回到第 1 页，否则会停在一个可能已不存在的页码上。
 */
watch(
  () => props.params,
  (next) => {
    page.value = next?.page ?? 1
    void load()
  },
  { immediate: true, deep: true }
)
</script>

<style scoped>
/* 与聊天窗口的会话侧栏同一套磨砂底：列表项是透明行 + 悬停提亮，不描边、不铺白卡片 */
.xxai-history-list {
  display: flex;
  flex-direction: column;
  min-height: 0;
  gap: 8px;
  padding: 8px;
  border-radius: var(--agent-radius-md, 12px);
  background: var(--agent-glass-surface);
  backdrop-filter: var(--agent-glass-blur);
  -webkit-backdrop-filter: var(--agent-glass-blur);
  color: var(--agent-foreground, #0f172a);
  font-family: var(--agent-font-sans, inherit);
}

.xxai-history-hint {
  padding: 16px 12px;
  color: var(--agent-muted-foreground, #64748b);
  font-size: 13px;
}

.xxai-history-hint--error {
  color: #dc2626;
}

.xxai-history-hint--empty {
  text-align: center;
}

.xxai-history-items {
  flex: 1;
  min-height: 0;
  margin: 0;
  padding: 8px;
  list-style: none;
  overflow-y: auto;
  scrollbar-width: thin;
}

.xxai-history-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  border-radius: var(--agent-radius-md, 12px);
  cursor: pointer;
  transition: background 0.15s ease;
}

.xxai-history-item + .xxai-history-item {
  margin-top: 2px;
}

.xxai-history-item:hover {
  background: rgba(255, 255, 255, 0.75);
}

.xxai-history-item:focus-visible {
  outline: 2px solid var(--agent-primary, #0ea5e9);
  outline-offset: 2px;
}

.xxai-history-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.xxai-history-item-title {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  color: var(--agent-foreground, #0f172a);
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.xxai-history-item-status {
  flex: 0 0 auto;
  padding: 1px 8px;
  border-radius: var(--agent-radius-sm, 6px);
  background: rgba(148, 163, 184, 0.2);
  color: var(--agent-muted-foreground, #64748b);
  font-size: 11px;
}

.xxai-history-item-status.is-deleted {
  background: rgba(254, 226, 226, 0.85);
  color: #dc2626;
}

.xxai-history-item-status.is-archived {
  background: rgba(254, 243, 199, 0.85);
  color: #b45309;
}

.xxai-history-item-preview {
  overflow: hidden;
  color: var(--agent-muted-foreground, #64748b);
  font-size: 12px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.xxai-history-item-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  color: var(--agent-muted-foreground, #64748b);
  font-size: 12px;
}

.xxai-history-item-time {
  margin-left: auto;
}

.xxai-history-pager {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding-top: 8px;
  border-top: 1px solid rgba(226, 232, 240, 0.9);
}

.xxai-history-page-btn {
  min-height: 28px;
  padding: 0 12px;
  border: 1px solid rgba(100, 116, 139, 0.25);
  border-radius: var(--agent-radius-sm, 6px);
  background: rgba(255, 255, 255, 0.8);
  color: inherit;
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}

.xxai-history-page-btn:hover:not(:disabled) {
  border-color: var(--agent-primary, #0ea5e9);
  color: var(--agent-primary, #0ea5e9);
}

.xxai-history-page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.xxai-history-page-label {
  color: var(--agent-muted-foreground, #64748b);
  font-size: 12px;
}
</style>
