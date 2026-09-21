import { AgentClient } from './core'
import {
  configureMarkdownDiagrams,
  createChatUI,
  registerCustomComponent,
  registerMarkdownFenceRenderer
} from './ui'
import { createApp, h } from 'vue'
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
      window: options.ui?.window,
      layout: options.ui?.layout,
      sidebar: options.ui?.sidebar,
      showAgentSteps: options.ui?.showAgentSteps
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

export { ChatWidget, MarkdownContent } from './ui'

export { configureMarkdownDiagrams, registerCustomComponent, registerMarkdownFenceRenderer }

export type {
  EChartsLike,
  MarkdownDiagramOptions,
  MarkdownFenceContext,
  MarkdownFenceRenderer,
  MarkdownFenceRendererInput,
  MermaidLike
} from './ui'

export { createApp, h }

export { AgentClient } from './core'
