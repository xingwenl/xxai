import type { ToolDefinition } from '../types'

export type PageElementRole =
  | 'button' | 'link' | 'textbox' | 'checkbox' | 'radio' | 'combobox'
  | 'tab' | 'select' | 'other'

export interface PageElement {
  ref: string
  role: PageElementRole
  name: string
  value?: string
  checked?: boolean
  disabled?: boolean
  expanded?: boolean
  required?: boolean
}

export interface PageSnapshot {
  snapshotId: string
  url: string
  title: string
  viewport: { width: number; height: number; scrollX: number; scrollY: number }
  text: string
  elements: PageElement[]
  truncated: boolean
}

export interface PageToolsOptions {
  enabled?: boolean
  confirmationKeywords?: string[]
  maxCalls?: number
  maxDurationMs?: number
}

export interface PageToolRuntime {
  snapshot(): PageSnapshot
  currentSnapshot(): PageSnapshot
  resolve(snapshotId: string, ref: string): Element
  isConfirmationRequired(element: Element, action: 'click' | 'type'): boolean
}

export type PageToolDefinition = ToolDefinition
