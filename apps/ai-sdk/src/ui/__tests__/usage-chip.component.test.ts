// @vitest-environment jsdom
// chip 是交互式展开（点击后出现明细卡），SSR 只能覆盖收起态，故用 jsdom 真点一次。
import { afterEach, describe, expect, it } from 'vitest'
import { createApp, nextTick, type App } from 'vue'
import type { ModelUsage } from '../../core'
import UsageChip from '../components/UsageChip.vue'

const usage: ModelUsage = {
  promptTokens: 1_319_322,
  completionTokens: 12_823,
  totalTokens: 1_332_145,
  cacheReadTokens: 1_239_936,
  model: 'deepseek/deepseek-v4.1-flash',
  provider: 'ds1'
}

let app: App | null = null
let host: HTMLElement | null = null

async function mount(value: ModelUsage | null): Promise<HTMLElement> {
  host = document.createElement('div')
  document.body.appendChild(host)
  app = createApp(UsageChip, { usage: value })
  app.mount(host)
  await nextTick()
  return host
}

afterEach(() => {
  app?.unmount()
  app = null
  host?.remove()
  host = null
})

describe('UsageChip', () => {
  it('默认只渲染 chip，明细卡收起', async () => {
    const el = await mount(usage)

    const chip = el.querySelector('.xxai-usage-chip')
    expect(chip?.textContent).toContain('用量 1.3M tok')
    expect(chip?.getAttribute('aria-expanded')).toBe('false')
    expect(chip?.getAttribute('title')).toBe('1,332,145 tok')
    expect(el.querySelector('.xxai-usage-panel')).toBeNull()
  })

  it('点击 chip 展开明细卡，再点收起', async () => {
    const el = await mount(usage)
    const chip = el.querySelector<HTMLButtonElement>('.xxai-usage-chip')

    chip?.click()
    await nextTick()

    const panel = el.querySelector('.xxai-usage-panel')
    expect(panel).not.toBeNull()
    expect(chip?.getAttribute('aria-expanded')).toBe('true')
    expect(panel?.textContent).toContain('本轮用量')
    expect(panel?.textContent).toContain('1,332,145 tok')
    expect(panel?.textContent).toContain('ds1 / deepseek/deepseek-v4.1-flash')
    expect(panel?.textContent).toContain('94%')

    chip?.click()
    await nextTick()

    expect(el.querySelector('.xxai-usage-panel')).toBeNull()
    expect(chip?.getAttribute('aria-expanded')).toBe('false')
  })

  it('没有用量时整块不渲染', async () => {
    const el = await mount(null)

    expect(el.querySelector('.xxai-usage-chip')).toBeNull()
    expect(el.querySelector('.xxai-usage-panel')).toBeNull()
  })
})
