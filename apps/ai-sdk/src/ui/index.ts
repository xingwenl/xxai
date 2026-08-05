import { createApp, type App } from 'vue'
import ChatWidget from './components/ChatWidget.vue'
import type { AgentClient } from '../core'
import type { UIColors } from '../core'
export { registerCustomComponent } from './registry'

export function createChatUI(agent: AgentClient, options?: {
  position?: 'left' | 'right'
  theme?: 'light' | 'dark' | 'auto'
  title?: string
  colors?: UIColors
  container?: HTMLElement
}): {
  app: App
  destroy: () => void
} {
  const container = options?.container || document.body
  const mountPoint = document.createElement('div')
  container.appendChild(mountPoint)

  const app = createApp(ChatWidget, {
    agent,
    position: options?.position || 'right',
    theme: options?.theme || 'auto',
    title: options?.title || 'AI Assistant',
    colors: options?.colors
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
