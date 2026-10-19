import { describe, expect, it } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import ContextRing from '../components/ContextRing.vue'
import { contextRingState } from '../context-ring'

function render(state: ReturnType<typeof contextRingState>) {
  return renderToString(createSSRApp({ render: () => h(ContextRing, { state }) }))
}

describe('ContextRing', () => {
  it('把占用文本渲染出来（QuotaRing 里这段文本是注释掉的）', async () => {
    const html = await render(contextRingState(12300, 1_000_000))

    expect(html).toContain('xxai-context-ring')
    expect(html).toContain('12.3K/1.0M (1%)')
  })

  it('接近窗口上限时使用危险色描边', async () => {
    const html = await render(contextRingState(950_000, 1_000_000))

    expect(html).toContain('#EF4444')
    expect(html).toContain('950.0K/1.0M (95%)')
  })

  it('窗口未知（state 为 null）时整块不渲染', async () => {
    const html = await render(null)

    expect(html).not.toContain('xxai-context-ring')
  })
})
