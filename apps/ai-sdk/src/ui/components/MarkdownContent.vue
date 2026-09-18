<template>
  <div ref="rootElement" class="xxai-markdown-content" v-html="html"></div>
</template>

<script setup lang="ts">
import DOMPurify from 'dompurify'
import { computed, h, nextTick, onBeforeUnmount, ref, render, watch } from 'vue'
import type { AgentClient } from '../../core'
import MarkdownDiagram from './MarkdownDiagram.vue'
import { resolveDiagramTheme } from '../markdown'
import { renderMarkdown } from '../markdown/pipeline'

const props = defineProps<{ text?: string; agent?: AgentClient }>()

// 每次文本变化都重建占位 id 与源码映射，避免流式更新后残留旧图表源码
const rendered = computed(() => renderMarkdown(props.text))
const html = computed(() => DOMPurify.sanitize(rendered.value.html, {
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

// 占位节点 → 已挂载的图表组件记录，用于区分「DOM 未变，仅源码更新」与「需要重新挂载」
const mountedDiagrams = new Map<HTMLElement, { id: string; theme: 'light' | 'dark' }>()

async function hydrateDiagrams() {
  await nextTick()
  const container = rootElement.value
  if (!container) return

  const seen = new Set<HTMLElement>()
  const placeholders = Array.from(container.querySelectorAll<HTMLElement>('[data-xxai-diagram-id]'))
  for (const placeholder of placeholders) {
    const id = placeholder.dataset.xxaiDiagramId || ''
    const source = rendered.value.diagrams.get(id)
    if (!source) continue
    seen.add(placeholder)

    const mounted = mountedDiagrams.get(placeholder)
    if (mounted && mounted.id === id) {
      // 占位节点仍然存在（HTML 未变或仅源码变化）：把新源码推给已挂载的组件，
      // 由组件内部按源码变化重绘，避免重复初始化引擎导致闪烁
      render(h(MarkdownDiagram, {
        code: source.code,
        language: source.language,
        theme: mounted.theme
      }), placeholder)
      continue
    }

    const theme = resolveDiagramTheme(placeholder)
    render(h(MarkdownDiagram, {
      code: source.code,
      language: source.language,
      theme
    }), placeholder)
    mountedDiagrams.set(placeholder, { id, theme })
  }

  // v-html 替换 DOM 后旧占位节点会变成游离节点，这里统一卸载清理
  for (const placeholder of Array.from(mountedDiagrams.keys())) {
    if (seen.has(placeholder)) continue
    render(null, placeholder)
    mountedDiagrams.delete(placeholder)
  }
}

watch(html, hydrateImages, { immediate: true })
// 图表源码不在 HTML 里，必须监听渲染结果对象，否则「HTML 不变但源码变化」不会重绘
watch(rendered, hydrateDiagrams, { immediate: true })
onBeforeUnmount(() => {
  for (const placeholder of Array.from(mountedDiagrams.keys())) render(null, placeholder)
  mountedDiagrams.clear()
  for (const objectUrl of objectUrls) URL.revokeObjectURL(objectUrl)
  objectUrls.clear()
})
</script>
