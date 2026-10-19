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
  AgentError,
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
  AgentError,
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

// 接入方需要知道「自己这份 SDK 说的是哪个协议版本、自己是什么版本」，
// 才能在兼容性报错与日志里对上号，因此从包根导出。
export { PROTOCOL_VERSION, SDK_VERSION } from './core/protocol'

export { ConversationList, ConversationHistory } from './history'

export type {
  ConversationSummaryPayload,
  ConversationPagePayload,
  ConversationLoopStepPayload,
  ConversationLoopRunPayload,
  ConversationMessagePayload,
  ConversationListParams,
  ConversationHistorySource,
  HistoryMessageLike
} from './history'
