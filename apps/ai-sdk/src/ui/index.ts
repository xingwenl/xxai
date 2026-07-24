import { createApp, type Component, type App } from 'vue'
import ChatWidget from './components/ChatWidget.vue'
import type { AgentClient } from '../core'

const registeredComponents: Record<string, Component> = {}

export function registerCustomComponent(name: string, component: Component) {
  registeredComponents[name] = component
}

export function createChatUI(agent: AgentClient, options?: {
  position?: 'left' | 'right'
  theme?: 'light' | 'dark' | 'auto'
  title?: string
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
    title: options?.title || 'AI Assistant'
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
