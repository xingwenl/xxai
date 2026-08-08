import { AgentClient } from './core'
import { createChatUI, registerCustomComponent } from './ui'
import type {
  AgentClientOptions,
  AgentCallbacks,
  Message,
  TokenProviderContext,
  ToolConfirmation,
  ToolDefinition,
  ToolSideEffect,
  ToolType,
  UIOptions,
  UIColors
} from './core'

export function createAgentClient(options: AgentClientOptions) {
  const agent = new AgentClient(options)

  if (options.ui?.mode !== 'headless') {
    createChatUI(agent, {
      position: options.ui?.position,
      theme: options.ui?.theme,
      colors: options.ui?.colors,
      container: options.ui?.container
    })
  }

  return agent
}

export type {
  AgentClientOptions,
  AgentCallbacks,
  Message,
  TokenProviderContext,
  ToolConfirmation,
  ToolDefinition,
  ToolSideEffect,
  ToolType,
  UIOptions,
  UIColors
}

export type { PageElement, PageSnapshot, PageToolsOptions } from './core'

export { registerCustomComponent }

export { AgentClient } from './core'
