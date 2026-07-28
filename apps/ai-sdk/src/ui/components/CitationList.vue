<template>
  <ul v-if="citations.length" class="xxai-citations" aria-label="参考来源">
    <li v-for="(citation, index) in citations" :key="`${citation.title}-${index}`">
      <a v-if="citation.sourceUrl" :href="citation.sourceUrl" target="_blank" rel="noreferrer">{{ citation.title || `来源 ${index + 1}` }}</a>
      <span v-else>{{ citation.title || `来源 ${index + 1}` }}</span>
      <small v-if="citation.text">{{ citation.text }}</small>
    </li>
  </ul>
</template>
<script setup lang="ts">
defineProps<{ citations: Array<{ title?: string; text?: string; sourceUrl?: string }> }>()
</script>
