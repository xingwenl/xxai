import { createApp, type App } from 'vue'
import ChatWidget from './components/ChatWidget.vue'
import type { AgentClient } from '../core'
import type { UIColors, UIOptions, UIWindowBounds } from '../core'
export { registerCustomComponent } from './registry'
export { default as MarkdownContent } from './components/MarkdownContent.vue'
export {
  configureMarkdownDiagrams,
  getMarkdownFenceRenderer,
  isMermaidSourceReady,
  listMarkdownFenceLanguages,
  normalizeFenceLanguage,
  parseEChartsOption,
  registerMarkdownFenceRenderer,
  resolveDiagramTheme,
  sanitizeMermaidSource,
  unregisterMarkdownFenceRenderer,
  type EChartsInstanceLike,
  type EChartsLike,
  type MarkdownDiagramOptions,
  type MarkdownFenceCleanup,
  type MarkdownFenceContext,
  type MarkdownFenceRenderer,
  type MarkdownFenceRendererInput,
  type MermaidLike
} from './markdown'

export function createChatUI(agent: AgentClient, options?: {
  position?: 'left' | 'right'
  theme?: 'light' | 'dark' | 'auto'
  title?: string
  colors?: UIColors
  container?: HTMLElement
  window?: UIWindowBounds
  layout?: UIOptions['layout']
  sidebar?: UIOptions['sidebar']
}): {
  app: App
  destroy: () => void
} {
  const embedded = Boolean(options?.container)
  const container = options?.container || document.body
  const mountPoint = document.createElement('div')
  container.appendChild(mountPoint)

  // 嵌入式模式：挂载点铺满容器，让聊天窗口以绝对定位填满容器。
  if (embedded) {
    mountPoint.style.position = 'relative'
    mountPoint.style.width = '100%'
    mountPoint.style.height = '100%'
  }

  const app = createApp(ChatWidget, {
    agent,
    position: options?.position || 'right',
    theme: options?.theme || 'auto',
    title: options?.title || 'AI Assistant',
    colors: options?.colors,
    window: options?.window,
    layout: options?.layout || 'single',
    sidebarWidth: options?.sidebar?.width,
    embedded
  })

  app.mount(mountPoint)

  agent._setUIMounted(true)
  agent._setUIContainer(mountPoint)

  return {
    app,
    destroy: () => {
      app.unmount()
      mountPoint.remove()
      agent._setUIMounted(false)
      agent._setUIContainer(null)
    }
  }
}

export { ChatWidget }
