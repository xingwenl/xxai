import { AgentClient } from './core'
import { createChatUI, registerCustomComponent } from './ui'
import type { AgentClientOptions, AgentCallbacks, Message, TokenProviderContext, ToolDefinition, UIOptions } from './core'

export function createAgentClient(options: AgentClientOptions) {
  const agent = new AgentClient(options)

  if (options.ui?.mode !== 'headless') {
    createChatUI(agent, {
      position: options.ui?.position,
      theme: options.ui?.theme,
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
  ToolDefinition,
  UIOptions
}

export { registerCustomComponent }

export { AgentClient } from './core'
