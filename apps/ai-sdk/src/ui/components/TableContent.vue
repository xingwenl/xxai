<template>
  <div class="xxai-table-content">
    <table v-if="columns.length">
      <thead>
        <tr><th v-for="column in columns" :key="column.key">{{ column.label }}</th></tr>
      </thead>
      <tbody>
        <tr v-for="(row, index) in rows" :key="index">
          <td v-for="column in columns" :key="column.key">{{ row[column.key] }}</td>
        </tr>
      </tbody>
    </table>
    <span v-else>{{ block.fallback || '表格暂不可用' }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { MessageContentBlock } from '../../core'

type TableColumn = { key: string; label: string }
type StructuredBlock = MessageContentBlock & {
  props?: { columns?: TableColumn[]; rows?: Array<Record<string, unknown>> }
  metadata?: { columns?: TableColumn[]; rows?: Array<Record<string, unknown>> }
}

const props = defineProps<{ block: MessageContentBlock }>()
const block = props.block as StructuredBlock
const data = computed(() => block.props || block.metadata || {})
const columns = computed(() => Array.isArray(data.value.columns) ? data.value.columns : [])
const rows = computed(() => Array.isArray(data.value.rows) ? data.value.rows : [])
</script>
