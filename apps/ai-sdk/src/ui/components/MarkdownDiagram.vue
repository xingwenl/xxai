<template>
  <div class="xxai-markdown-diagram">
    <!-- 引擎需要真实布局尺寸（ECharts 会读取容器宽高），因此只在降级时隐藏画布 -->
    <div ref="containerElement" class="xxai-markdown-diagram-canvas" :hidden="state === 'fallback'"></div>
    <template v-if="state !== 'rendered'">
      <pre><code :class="`language-${language}`">{{ code }}</code></pre>
      <p v-if="state === 'fallback'" class="xxai-markdown-diagram-hint">{{ fallbackHint }}</p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  getMarkdownFenceErrorCode,
  getMarkdownFenceRenderer,
  type MarkdownFenceCleanup,
  type MarkdownFenceErrorCode
} from '../markdown/fence-registry'

const props = defineProps<{
  code: string
  language: string
  theme: 'light' | 'dark'
}>()

// loading：渲染器尚未返回；rendered：已成功绘制；fallback：渲染器不可用或源码不可渲染
const state = ref<'loading' | 'rendered' | 'fallback'>('loading')
const fallbackReason = ref<MarkdownFenceErrorCode | null>(null)
const containerElement = ref<HTMLElement | null>(null)
const fallbackHint = computed(() => describeFallback(props.language, fallbackReason.value))

let cleanup: MarkdownFenceCleanup | void
let generation = 0
let disposed = false

// 降级提示要能直接说明原因，否则用户只能看到“渲染失败”
function describeFallback(language: string, reason: MarkdownFenceErrorCode | null): string {
  const engineName = language === 'echarts' ? 'ECharts' : language === 'mermaid' ? 'Mermaid' : language
  if (reason === 'engine-missing') return `未检测到 ${engineName} 引擎，已显示源码`
  if (reason === 'source-not-ready') return '图表定义尚未完整，已显示源码'
  if (reason === 'option-invalid') return '图表配置不是合法的 JSON 对象，已显示源码'
  return '图表渲染不可用，已显示源码'
}

async function draw() {
  const element = containerElement.value
  const renderer = getMarkdownFenceRenderer(props.language)
  if (!element || !renderer) {
    state.value = 'fallback'
    return
  }

  const current = ++generation
  state.value = 'loading'
  cleanup?.()
  cleanup = undefined
  element.innerHTML = ''

  try {
    const nextCleanup = await renderer.mount(element, props.code, {
      theme: props.theme,
      language: props.language
    })
    // 渲染是异步的：期间源码或主题可能已变化，或组件已卸载，此时丢弃过期结果并立即清理
    if (disposed || current !== generation) {
      nextCleanup?.()
      return
    }
    cleanup = nextCleanup
    state.value = 'rendered'
  } catch (error) {
    if (disposed || current !== generation) return
    element.innerHTML = ''
    fallbackReason.value = getMarkdownFenceErrorCode(error)
    state.value = 'fallback'
  }
}

onMounted(() => {
  void draw()
})

watch(() => [props.code, props.theme, props.language], () => {
  void draw()
})

onBeforeUnmount(() => {
  disposed = true
  generation += 1
  cleanup?.()
  cleanup = undefined
})
</script>
