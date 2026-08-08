import type { PageElement, PageElementRole, PageSnapshot, PageToolRuntime } from './types'

const MAX_ELEMENTS = 200
const MAX_TEXT = 16 * 1024
const MAX_FIELD = 512
const DEFAULT_MAX_CALLS = 20
const HARD_MAX_CALLS = 100
const DEFAULT_MAX_DURATION_MS = 120_000
const HARD_MAX_DURATION_MS = 600_000
let snapshotSequence = 0

function visible(element: Element): boolean {
  if (!(element instanceof HTMLElement)) return false
  const style = getComputedStyle(element)
  if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false
  const rect = element.getBoundingClientRect()
  return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth
}

function roleOf(element: Element): PageElementRole {
  const explicit = element.getAttribute('role')
  if (explicit === 'button' || explicit === 'link' || explicit === 'textbox' || explicit === 'checkbox' || explicit === 'radio' || explicit === 'combobox' || explicit === 'tab') return explicit
  const tag = element.tagName.toLowerCase()
  if (tag === 'button' || (tag === 'input' && ['button', 'submit', 'reset'].includes((element as HTMLInputElement).type))) return 'button'
  if (tag === 'a' && element.getAttribute('href')) return 'link'
  if (tag === 'textarea' || (tag === 'input' && !['hidden', 'checkbox', 'radio', 'file', 'button', 'submit', 'reset'].includes((element as HTMLInputElement).type))) return 'textbox'
  if (tag === 'select') return 'select'
  if (tag === 'input' && (element as HTMLInputElement).type === 'checkbox') return 'checkbox'
  if (tag === 'input' && (element as HTMLInputElement).type === 'radio') return 'radio'
  if (element instanceof HTMLElement && element.isContentEditable) return 'textbox'
  return 'other'
}

function accessibleName(element: Element): string {
  const labelledBy = element.getAttribute('aria-labelledby')
  const label = labelledBy ? labelledBy.split(/\s+/).map(id => document.getElementById(id)?.textContent || '').join(' ') : ''
  const own = element.getAttribute('aria-label') || label || (element as HTMLInputElement).labels?.[0]?.textContent || element.textContent || element.getAttribute('title') || ''
  return own.replace(/\s+/g, ' ').trim().slice(0, MAX_FIELD)
}

function elementValue(element: Element): string | undefined {
  if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement) return element.value.slice(0, MAX_FIELD)
  if (element instanceof HTMLElement && element.isContentEditable) return (element.textContent || '').slice(0, MAX_FIELD)
  return undefined
}

function isInteractive(element: Element, role: PageElementRole): boolean {
  if (role !== 'other') return true
  return element instanceof HTMLElement && (element.tabIndex >= 0 || element.hasAttribute('onclick'))
}

export class PageRuntime implements PageToolRuntime {
  private current: { snapshot: PageSnapshot; refs: Map<string, Element> } | null = null
  private refSequence = 0
  private readonly confirmationKeywords: string[]
  private readonly maxCalls: number
  private readonly maxDurationMs: number
  private calls = 0
  private budgetStartedAt: number | null = null

  constructor(options?: { confirmationKeywords?: string[]; maxCalls?: number; maxDurationMs?: number }) {
    this.confirmationKeywords = (options?.confirmationKeywords || ['提交', '删除', '支付', '转账', '确认', '退出', 'submit', 'delete', 'pay', 'transfer', 'confirm']).map(item => item.toLowerCase())
    this.maxCalls = Math.min(Math.max(Math.floor(options?.maxCalls ?? DEFAULT_MAX_CALLS), 1), HARD_MAX_CALLS)
    this.maxDurationMs = Math.min(Math.max(Math.floor(options?.maxDurationMs ?? DEFAULT_MAX_DURATION_MS), 1000), HARD_MAX_DURATION_MS)
  }

  consumeBudget(): void {
    const now = Date.now()
    if (this.budgetStartedAt === null) this.budgetStartedAt = now
    if (this.calls >= this.maxCalls || now - this.budgetStartedAt >= this.maxDurationMs) throw new Error('page_tool_budget_exceeded')
    this.calls += 1
  }

  snapshot(): PageSnapshot {
    if (typeof document === 'undefined' || typeof window === 'undefined') throw new Error('page_unavailable')
    const refs = new Map<string, Element>()
    const elements: PageElement[] = []
    const nodes = Array.from(document.body?.querySelectorAll('*') || [])
    for (const element of nodes) {
      if (!visible(element)) continue
      const role = roleOf(element)
      if (!isInteractive(element, role)) continue
      const ref = `e_${++this.refSequence}`
      refs.set(ref, element)
      const item: PageElement = { ref, role, name: accessibleName(element) || role }
      const value = elementValue(element)
      if (value !== undefined) item.value = value
      if (element instanceof HTMLInputElement && ['checkbox', 'radio'].includes(element.type)) item.checked = element.checked
      if (element.hasAttribute('disabled') || (element instanceof HTMLButtonElement && element.disabled)) item.disabled = true
      if (element.hasAttribute('aria-expanded')) item.expanded = element.getAttribute('aria-expanded') === 'true'
      if (element.hasAttribute('required') || element.getAttribute('aria-required') === 'true') item.required = true
      elements.push(item)
      if (elements.length >= MAX_ELEMENTS) break
    }
    const bodyText = (document.body?.innerText || '').replace(/\s+/g, ' ').trim()
    const text = bodyText.slice(0, MAX_TEXT)
    const snapshot: PageSnapshot = {
      snapshotId: `s_${++snapshotSequence}`,
      url: `${location.origin}${location.pathname}`,
      title: document.title.slice(0, MAX_FIELD),
      viewport: { width: innerWidth, height: innerHeight, scrollX: scrollX, scrollY: scrollY },
      text,
      elements,
      truncated: bodyText.length > MAX_TEXT || nodes.length > MAX_ELEMENTS
    }
    this.current = { snapshot, refs }
    return snapshot
  }

  currentSnapshot(): PageSnapshot {
    if (!this.current) throw new Error('page_snapshot_required')
    return this.current.snapshot
  }

  resolve(snapshotId: string, ref: string): Element {
    if (!this.current || this.current.snapshot.snapshotId !== snapshotId) throw new Error('page_snapshot_stale')
    const element = this.current.refs.get(ref)
    if (!element || !element.isConnected || !visible(element)) throw new Error('page_element_not_visible')
    const item = this.current.snapshot.elements.find(candidate => candidate.ref === ref)
    if (!item || roleOf(element) !== item.role || accessibleName(element) !== item.name) throw new Error('page_snapshot_stale')
    return element
  }

  isConfirmationRequired(element: Element, action: 'click' | 'type'): boolean {
    if (action === 'type') return false
    const text = `${accessibleName(element)} ${element.getAttribute('type') || ''}`.toLowerCase()
    return this.confirmationKeywords.some(keyword => text.includes(keyword)) || element.tagName.toLowerCase() === 'a'
  }
}
