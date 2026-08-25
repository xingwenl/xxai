<template>
  <div ref="rootElement" class="xxai-markdown-content" v-html="html"></div>
</template>

<script setup lang="ts">
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { AgentClient } from '../../core'

const props = defineProps<{ text?: string; agent?: AgentClient }>()
const parser = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  typographer: true
})

function escapeAttribute(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[character] || character)
}

// 先把图片地址放入 data 属性，避免 v-html 插入时由浏览器直接发起未授权请求。
parser.renderer.rules.image = (tokens, index, _options, _env, _self) => {
  const token = tokens[index]
  const source = String(token.attrGet('src') || '')
  const alt = String(token.content || '')
  const title = token.attrGet('title')
  const titleAttribute = title ? ` title="${escapeAttribute(String(title))}"` : ''
  return `<img data-xxai-image-src="${escapeAttribute(source)}" alt="${escapeAttribute(alt)}"${titleAttribute}>`
}

const html = computed(() => DOMPurify.sanitize(parser.render(props.text || ''), {
  USE_PROFILES: { html: true }
}))

const objectUrls = new Set<string>()
const rootElement = ref<HTMLElement | null>(null)

function isProtectedAssetUrl(source: string): boolean {
  try {
    const parsed = new URL(source, window.location.href)
    return parsed.pathname.startsWith('/api/v1/assets/')
  } catch {
    return source.startsWith('/api/v1/assets/')
  }
}

async function hydrateImages() {
  await nextTick()
  const container = rootElement.value
  if (!container) return
  const images = Array.from(container.querySelectorAll<HTMLImageElement>('img[data-xxai-image-src]'))
  await Promise.all(images.map(async (image) => {
    const source = image.dataset.xxaiImageSrc || ''
    if (!source) return
    try {
      if (isProtectedAssetUrl(source)) {
        if (!props.agent) return
        const objectUrl = await props.agent.loadAsset(source)
        objectUrls.add(objectUrl)
        image.src = objectUrl
      } else {
        image.src = source
      }
      image.removeAttribute('data-xxai-image-src')
    } catch {
      image.alt = `${image.alt || '图片'}（加载失败）`
    }
  }))
}

watch(html, hydrateImages, { immediate: true })
onBeforeUnmount(() => {
  for (const objectUrl of objectUrls) URL.revokeObjectURL(objectUrl)
  objectUrls.clear()
})
</script>
