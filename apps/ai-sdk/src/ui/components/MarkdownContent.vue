<template>
  <div class="xxai-markdown-content" v-html="html"></div>
</template>

<script setup lang="ts">
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import { computed } from 'vue'

const props = defineProps<{ text?: string }>()
const parser = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  typographer: true
})

const html = computed(() => DOMPurify.sanitize(parser.render(props.text || ''), {
  USE_PROFILES: { html: true }
}))
</script>
