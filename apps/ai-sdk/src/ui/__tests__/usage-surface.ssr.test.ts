// @vitest-environment jsdom
// 走真实 MarkdownContent（DOMPurify 依赖 window），与 chat-message.ssr.test.ts 同环境。
import { describe, expect, it } from 'vitest'
import { createSSRApp, h, type Component } from 'vue'
import { renderToString } from '@vue/server-renderer'
import type { Message } from '../../core'
import ChatMessage from '../components/ChatMessage.vue'
import ChatMessageList from '../components/ChatMessageList.vue'

const usage = {
  prompt_tokens: 1_319_322,
  completion_tokens: 12_823,
  total_tokens: 1_332_145,
  cache_read_tokens: 1_239_936,
  model: 'deepseek/deepseek-v4.1-flash',
  provider: 'ds1'
}

function message(overrides: Partial<Message> = {}): Message {
  return {
    id: 'm1',
    role: 'assistant',
    type: 'text',
    content: { type: 'text', text: '回答' },
    timestamp: new Date(),
    ...overrides
  }
}

function render(component: Component, props: Record<string, unknown>) {
  return renderToString(
    createSSRApp({ render: () => h(component, props) })
  )
}

describe('逐轮用量 chip 的渲染面', () => {
  it('assistant 消息带用量时渲染 chip', async () => {
    const html = await render(ChatMessage, {
      message: message({ metadata: { usage } })
    })

    expect(html).toContain('xxai-usage-chip')
    expect(html).toContain('用量 1.3M tok')
    // 收起态不渲染明细卡。
    expect(html).not.toContain('xxai-usage-panel')
  })

  it('用户消息即便带了用量也不渲染 chip（只标注模型消耗）', async () => {
    const html = await render(ChatMessage, {
      message: message({ role: 'user', metadata: { usage } })
    })

    expect(html).not.toContain('xxai-usage-chip')
  })

  it('没有用量或用量非法时不渲染 chip', async () => {
    expect(await render(ChatMessage, { message: message() })).not.toContain('xxai-usage-chip')
    expect(
      await render(ChatMessage, { message: message({ metadata: { usage: { prompt_tokens: 1 } } }) })
    ).not.toContain('xxai-usage-chip')
  })
})

describe('会话累计行', () => {
  it('按已加载消息求和后渲染在列表末尾', async () => {
    const html = await render(ChatMessageList, {
      messages: [
        message({ id: 'm1', metadata: { usage } }),
        message({
          id: 'm2',
          metadata: {
            usage: {
              prompt_tokens: 100,
              completion_tokens: 20,
              total_tokens: 120,
              cache_read_tokens: 60
            }
          }
        })
      ]
    })

    expect(html).toContain('xxai-session-usage')
    expect(html).toContain('本会话累计 1.3M tok')
    // 合计命中率 = (1,239,936 + 60) / (1,319,322 + 100) ≈ 94%
    expect(html).toContain('缓存命中 94%')
  })

  it('没有任何用量时不渲染累计行', async () => {
    const html = await render(ChatMessageList, { messages: [message()] })

    expect(html).not.toContain('xxai-session-usage')
  })
})
