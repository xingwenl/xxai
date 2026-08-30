import { AgentClient } from './core'
import { createChatUI, registerCustomComponent } from './ui'
import { h } from 'vue'
import type {
  AgentClientOptions,
  AgentCallbacks,
  AgentQuestion,
  Message,
  QuestionAnswer,
  QuestionOption,
  TokenProviderContext,
  ToolConfirmation,
  ToolDefinition,
  ToolSideEffect,
  ToolType,
  UIOptions,
  UIColors,
  UIWindowBounds
} from './core'

export function createAgentClient(options: AgentClientOptions) {
  const agent = new AgentClient(options)

  if (options.ui?.mode !== 'headless') {
    createChatUI(agent, {
      position: options.ui?.position,
      theme: options.ui?.theme,
      colors: options.ui?.colors,
      container: options.ui?.container,
      window: options.ui?.window
    })
  }

  return agent
}

export type {
  AgentClientOptions,
  AgentCallbacks,
  AgentQuestion,
  Message,
  QuestionAnswer,
  QuestionOption,
  TokenProviderContext,
  ToolConfirmation,
  ToolDefinition,
  ToolSideEffect,
  ToolType,
  UIOptions,
  UIColors,
  UIWindowBounds
}

export type { PageElement, PageSnapshot, PageToolsOptions } from './core'

export { registerCustomComponent }

export { h }

export { AgentClient } from './core'
