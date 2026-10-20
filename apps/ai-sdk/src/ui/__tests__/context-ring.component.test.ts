import { describe, expect, it } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import ContextRing from '../components/ContextRing.vue'
import { contextRingState } from '../context-ring'

function render(state: ReturnType<typeof contextRingState>) {
  return renderToString(createSSRApp({ render: () => h(ContextRing, { state }) }))
}

describe('ContextRing', () => {
  it('环旁渲染百分比文本，绝对量只进 title 提示', async () => {
    const html = await render(contextRingState(12300, 1_000_000))

    expect(html).toContain('xxai-context-ring')
    // 环旁边的可见文本只有百分比。
    expect(html).toContain('>1%<')
    expect(html).not.toContain('12.3K / 1.0M</span>')
    // 完整口径仍在悬停提示里（缺省提示 = 百分比 + 括号里的绝对量）。
    expect(html).toContain('title="1%（12.3K / 1.0M）"')
  })

  it('接近窗口上限时使用危险色描边', async () => {
    const html = await render(contextRingState(950_000, 1_000_000))

    expect(html).toContain('#EF4444')
    expect(html).toContain('>95%<')
  })

  it('调用方给了 title 时优先用它', async () => {
    const html = await renderToString(
      createSSRApp({
        render: () => h(ContextRing, { state: contextRingState(12300, 1_000_000), title: '上下文已用 1%' })
      })
    )

    expect(html).toContain('title="上下文已用 1%"')
  })

  it('窗口未知（state 为 null）时整块不渲染', async () => {
    const html = await render(null)

    expect(html).not.toContain('xxai-context-ring')
  })
})
