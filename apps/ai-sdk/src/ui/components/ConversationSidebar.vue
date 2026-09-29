<template>
  <aside
    class="xxai-conversation-sidebar"
    :class="{ 'is-collapsed': collapsed }"
    :style="{ '--xxai-sidebar-width': `${sidebarWidth}px` }"
    :aria-label="collapsed ? '展开会话列表' : '会话列表'"
  >
    <!-- 内层固定满宽并整体淡出：收起时是「内容滑走」而不是文字被挤变形。
         抽屉形态的位移开合由窗口类名驱动，组件本身不感知宽窄。 -->
    <div class="xxai-sidebar-inner">
      <div class="xxai-sidebar-head">
        <span class="xxai-sidebar-title">会话</span>
        <button
          class="xxai-sidebar-icon-btn"
          type="button"
          title="新建会话"
          aria-label="新建会话"
          :disabled="creating"
          @click="emit('create')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>
      </div>

      <div v-if="loading" class="xxai-sidebar-hint">正在加载…</div>
      <div v-else-if="error" class="xxai-sidebar-hint xxai-sidebar-hint--error">
        {{ error }}
        <button class="xxai-sidebar-retry" type="button" @click="emit('retry')">重试</button>
      </div>
      <div v-else-if="conversations.length === 0" class="xxai-sidebar-hint">
        还没有历史会话
      </div>

      <ul v-else class="xxai-sidebar-list">
        <li v-for="item in conversations" :key="item.id">
          <div
            class="xxai-sidebar-item"
            :class="{ 'is-active': String(item.id) === activeId }"
            role="button"
            tabindex="0"
            :title="item.title || '未命名会话'"
            @click="emit('select', item.id)"
            @keydown.enter.prevent="emit('select', item.id)"
            @keydown.space.prevent="emit('select', item.id)"
          >
            <div class="xxai-sidebar-item-main">
              <div class="xxai-sidebar-item-title">{{ item.title || '未命名会话' }}</div>
              <div class="xxai-sidebar-item-preview">
                {{ item.lastMessagePreview || '暂无消息' }}
              </div>
            </div>
            <button
              class="xxai-sidebar-delete"
              type="button"
              title="删除会话"
              :aria-label="`删除会话 ${item.title || item.id}`"
              @click.stop="emit('delete', item.id)"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6h14Z" />
              </svg>
            </button>
          </div>
        </li>
      </ul>
    </div>
  </aside>
</template>

<script setup lang="ts">
import type { ConversationSummary } from '../../core'

interface Props {
  conversations: ConversationSummary[]
  activeId?: string
  loading?: boolean
  error?: string
  creating?: boolean
  sidebarWidth?: number
  /** 宽屏下是否收起为 0 宽（窄屏抽屉用位移开合，不置此标志）。 */
  collapsed?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  activeId: undefined,
  loading: false,
  error: '',
  creating: false,
  sidebarWidth: 260,
  collapsed: false
})

const emit = defineEmits<{
  select: [id: number]
  create: []
  delete: [id: number]
  retry: []
}>()
</script>
