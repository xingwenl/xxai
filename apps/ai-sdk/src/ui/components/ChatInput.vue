<template>
  <div class="xxai-chat-input-wrapper">
    <!-- 附件预览列表 -->
    <div v-if="attachments.length > 0" class="xxai-attachment-list">
      <div
        v-for="att in attachments"
        :key="att.id"
        class="xxai-attachment-item"
        :class="{ 'xxai-attachment-error': att.state === 'failed' }"
      >
        <!-- 图片缩略图 -->
        <img
          v-if="att.thumbnailUrl"
          :src="att.thumbnailUrl"
          :alt="att.filename"
          class="xxai-attachment-thumb"
        />
        <!-- 文档图标 -->
        <div v-else class="xxai-attachment-icon">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M14 2v6h6" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>
        </div>
        <div class="xxai-attachment-info">
          <span class="xxai-attachment-name">{{ att.filename }}</span>
          <span class="xxai-attachment-meta">
            {{ formatSize(att.size) }}
            <span v-if="att.state === 'uploading'" class="xxai-attachment-status">上传中 {{ att.progress }}%</span>
            <span v-else-if="att.state === 'processing'" class="xxai-attachment-status">解析中...</span>
            <span v-else-if="att.state === 'ready'" class="xxai-attachment-status xxai-ready">就绪</span>
            <span v-else-if="att.state === 'failed'" class="xxai-attachment-status xxai-error">{{ att.errorMessage || '失败' }}</span>
          </span>
        </div>
        <button
          class="xxai-attachment-remove"
          aria-label="移除附件"
          @click="removeAttachment(att.id)"
        >&times;</button>
      </div>
    </div>

    <div class="xxai-chat-input">
      <!-- 附件按钮 -->
      <button
        class="xxai-attach-button"
        aria-label="添加附件"
        @click="triggerFileInput"
        :disabled="isSending"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
      </button>
      <input
        ref="fileInput"
        type="file"
        class="xxai-file-input"
        multiple
        accept="image/png,image/jpeg,image/gif,image/webp,.txt,.md,.csv,.pdf,.docx,.xlsx,.pptx"
        @change="handleFileSelect"
      />
      <input
        v-model="inputText"
        type="text"
        placeholder="输入消息..."
        @keydown.enter="handleSend"
        @paste="handlePaste"
        :disabled="isSending"
      />
      <button v-if="!isSending" class="xxai-send-button" aria-label="发送消息" @click="handleSend" :disabled="!inputText.trim() && !hasReadyAttachments">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4.5 20 12 4 19.5 7 12 4 4.5Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M7 12h9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
      </button>
      <button v-else class="xxai-stop-button" type="button" aria-label="停止生成" @click="$emit('stop')"><span></span></button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { AttachmentEntry, AttachmentRef } from '../../core/types'

interface Props {
  isSending?: boolean
}

const { isSending = false } = defineProps<Props>();

const emit = defineEmits<{
  send: [text: string, attachments?: AttachmentRef[]]
  stop: []
  'upload-attachment': [file: File]
}>()

const inputText = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const attachments = ref<AttachmentEntry[]>([])

let attachmentId = 0

const hasReadyAttachments = computed(() =>
  attachments.value.some((a) => a.state === 'ready')
)

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function triggerFileInput() {
  fileInput.value?.click()
}

function handleFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  const files = input.files
  if (!files) return
  for (let i = 0; i < files.length; i++) {
    addFile(files[i])
  }
  input.value = ''
}

function handlePaste(event: ClipboardEvent) {
  const items = event.clipboardData?.items
  if (!items) return
  for (let i = 0; i < items.length; i++) {
    const item = items[i]
    if (item.type.startsWith('image/')) {
      const file = item.getAsFile()
      if (file) addFile(file)
    }
  }
}

function addFile(file: File) {
  const id = `att_${++attachmentId}_${Date.now()}`
  const entry: AttachmentEntry = {
    id,
    file,
    filename: file.name,
    mimeType: file.type || 'application/octet-stream',
    size: file.size,
    state: 'pending',
  }

  // 使用 Blob URL 即时预览，避免把图片 Base64 写入本地消息历史。
  if (file.type.startsWith('image/')) {
    entry.thumbnailUrl = URL.createObjectURL(file)
  }

  attachments.value.push(entry)
  emit('upload-attachment', file)
}

function removeAttachment(id: string) {
  attachments.value = attachments.value.filter((a) => a.id !== id)
}

function getReadyAttachments(): AttachmentRef[] {
  return attachments.value
    .filter((a) => a.state === 'ready' && a.assetId)
    .map((a) => ({
      assetId: a.assetId!,
      filename: a.filename,
      mimeType: a.mimeType,
      size: a.size,
      previewUrl: a.thumbnailUrl,
    }))
}

function handleSend() {
  const text = inputText.value.trim()
  const readyAtts = getReadyAttachments()
  if (text || readyAtts.length > 0) {
    emit('send', text, readyAtts.length > 0 ? readyAtts : undefined)
    inputText.value = ''
    // 发送后清除附件列表
    attachments.value = []
  }
}

// 暴露给父组件的方法
defineExpose({
  addFile,
  updateAttachment: (id: string, updates: Partial<AttachmentEntry>) => {
    const idx = attachments.value.findIndex((a) => a.id === id)
    if (idx !== -1) {
      attachments.value[idx] = { ...attachments.value[idx], ...updates }
    }
  },
  removeAttachment,
  clearAttachments: () => { attachments.value = [] },
  getAttachments: () => attachments.value,
})
</script>

<style scoped>
.xxai-attachment-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 4px 8px 0;
}

.xxai-attachment-item {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--agent-surface, rgba(255, 255, 255, 0.6));
  border-radius: 8px;
  padding: 4px 8px;
  max-width: 220px;
  border: 1px solid transparent;
}

.xxai-attachment-item.xxai-attachment-error {
  border-color: #ef4444;
  background: #fef2f2;
}

.xxai-attachment-thumb {
  width: 32px;
  height: 32px;
  object-fit: cover;
  border-radius: 4px;
  flex-shrink: 0;
}

.xxai-attachment-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--agent-muted-foreground);
}

.xxai-attachment-icon svg {
  width: 20px;
  height: 20px;
}

.xxai-attachment-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

.xxai-attachment-name {
  font-size: 11px;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.xxai-attachment-meta {
  font-size: 10px;
  color: var(--agent-muted-foreground);
  display: flex;
  gap: 4px;
}

.xxai-attachment-status.xxai-ready {
  color: #10b981;
}

.xxai-attachment-status.xxai-error {
  color: #ef4444;
}

.xxai-attachment-remove {
  background: none;
  border: none;
  padding: 0;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  color: var(--agent-muted-foreground);
  flex-shrink: 0;
}

.xxai-attachment-remove:hover {
  color: #ef4444;
}

/* 附件按钮保持弱化的图标按钮观感，尺寸与全局按钮一致。 */
.xxai-attach-button {
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  color: var(--agent-muted-foreground);
  cursor: pointer;
}

.xxai-attach-button:hover {
  background: var(--agent-surface, rgba(255, 255, 255, 0.6));
  color: var(--agent-primary);
}

.xxai-attach-button svg {
  width: 18px;
  height: 18px;
}

.xxai-file-input {
  display: none;
}

/* 输入区外框（底色、边框、模糊、投影）由全局 .xxai-chat-input-wrapper
   统一定义，组件内不再覆盖，避免两处声明互相打架。 */

.xxai-chat-input {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px;
}

/* 输入框外观（磨砂白底、圆角胶囊、边框、聚焦态）由全局
   .xxai-chat-input input 统一定义；这里只保留排版相关声明。 */
.xxai-chat-input input[type="text"] {
  flex: 1;
  font-size: 14px;
  color: var(--agent-foreground);
}

.xxai-chat-input input[type="text"]::placeholder {
  color: var(--agent-muted-foreground);
}

/* 尺寸、圆角与配色由全局 .xxai-chat-input button 统一，这里不再重复声明。 */
.xxai-send-button {
  flex-shrink: 0;
}

/* 禁用态统一由全局规则表达，组件内不再重复。 */

.xxai-send-button svg {
  width: 16px;
  height: 16px;
}

/* 同上：几何与配色统一由全局规则负责。 */
.xxai-stop-button {
  flex-shrink: 0;
}

.xxai-stop-button span {
  display: block;
  width: 12px;
  height: 12px;
  background: var(--agent-foreground);
  border-radius: 2px;
}
</style>
