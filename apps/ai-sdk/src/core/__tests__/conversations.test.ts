/**
 * 会话列表 / 切换 / 软删除的 SDK 侧行为测试。
 *
 * 重点覆盖切换会话时的状态重置：只要 `MessageStore`、pending 流式态或
 * 重放游标任一项没被重置，就会出现「历史消息 + 上一条流式回答」串台，
 * 或新会话事件被去重逻辑静默丢弃。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { AgentClient } from '../client'
import { WebSocketTransport } from '../websocket'

function createClient() {
  return new AgentClient({
    endpoint: 'ws://127.0.0.1:8000/api/v1/ws/agents/1',
    baseUrl: 'http://127.0.0.1:8000/api/v1',
    platformId: 'p',
    agentId: '1',
    user: { id: 'u' },
    storageKey: 'test-conversations',
    getToken: async () => 'token'
  })
}

/** 取出消息的纯文本，避免联合类型收窄噪声。 */
function textOf(message: { content: unknown }): string {
  const content = message.content as { type?: string; text?: string }
  return content.type === 'text' ? content.text || '' : ''
}

function jsonResponse(data: unknown) {
  return { ok: true, status: 200, json: async () => ({ success: true, code: 0, data }) }
}

afterEach(() => {
  vi.unstubAllGlobals()
  globalThis.localStorage?.clear?.()
})

describe('conversation list', () => {
  it('maps the paginated response and calls the embed conversations endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        items: [
          {
            id: 7,
            title: '第一轮',
            created_at: '2026-09-20T08:00:00Z',
            message_count: 4,
            last_message_preview: '最后一句'
          }
        ],
        total: 1,
        page: 1,
        page_size: 20
      })
    )
    vi.stubGlobal('fetch', fetchMock)

    const page = await createClient().listConversations()

    expect(String(fetchMock.mock.calls[0][0])).toBe(
      'http://127.0.0.1:8000/api/v1/embed/conversations?page=1&page_size=20'
    )
    expect(page.total).toBe(1)
    expect(page.items[0]).toEqual({
      id: 7,
      title: '第一轮',
      createdAt: '2026-09-20T08:00:00Z',
      messageCount: 4,
      lastMessagePreview: '最后一句'
    })
  })
})

describe('openConversation', () => {
  it('replaces local messages with the fetched history', async () => {
    const client = createClient()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      jsonResponse([
        { id: 1, role: 'user', content: '历史提问', created_at: '2026-09-20T08:00:00Z' },
        { id: 2, role: 'assistant', content: '历史回答', created_at: '2026-09-20T08:01:00Z' }
      ])
    ))

    const messages = await client.openConversation(42)

    expect(messages.map(textOf)).toEqual(['历史提问', '历史回答'])
    expect(client.getMessages().length).toBe(2)
    expect(client.currentConversationId).toBe('42')
  })

  it('clears stale streaming state so history does not get mixed with the previous answer', async () => {
    const client = createClient()
    // 模拟上一轮回答仍在流式中：pending 态必须先被清掉。
    ;(client as any).pendingAssistantMessage = { id: 'pending', text: '上一条流式片段' }
    ;(client as any).pendingLoop = { id: 'loop', requestId: 'r', status: 'running', steps: [] }
    ;(client as any).pendingCitations = [{ title: '旧引用' }]

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      jsonResponse([{ id: 1, role: 'user', content: '新会话历史', created_at: '2026-09-20T08:00:00Z' }])
    ))

    await client.openConversation(99)

    expect((client as any).pendingAssistantMessage).toBeNull()
    expect((client as any).pendingLoop).toBeNull()
    expect((client as any).pendingCitations).toEqual([])
    expect(client.getMessages().map(textOf)).toEqual(['新会话历史'])
  })

  it('resets the replay cursor and rebinds the transport conversation id', async () => {
    const client = createClient()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([])))
    const transport = (client as any).transport as WebSocketTransport
    // 会话 A 的事件已经推进过游标。
    transport.setConversationId('a')
    ;(transport as any)._lastSequence = 12

    await client.openConversation(77)

    // 新会话从 sequence=1 开始；游标不归零会被去重逻辑全部丢弃。
    expect(transport.lastSequence).toBe(0)
    expect((transport as any)._conversationId).toBe('77')
    expect(client.currentConversationId).toBe('77')
  })

  it('surfaces a failure instead of rendering an empty conversation', async () => {
    const client = createClient()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }))

    await expect(client.openConversation(404)).rejects.toThrow('历史消息加载失败: 404')
  })
})

describe('startNewConversation', () => {
  it('clears messages and unbinds the conversation id', async () => {
    const client = createClient()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      jsonResponse([{ id: 1, role: 'user', content: '旧会话', created_at: '2026-09-20T08:00:00Z' }])
    ))
    await client.openConversation(5)
    expect(client.getMessages().length).toBe(1)

    client.startNewConversation()

    expect(client.getMessages()).toEqual([])
    expect(client.currentConversationId).toBeUndefined()
    expect(((client as any).transport as WebSocketTransport).lastSequence).toBe(0)
  })
})

describe('deleteConversation', () => {
  it('issues a DELETE and falls back to a new conversation when deleting the current one', async () => {
    const client = createClient()
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse([
        { id: 1, role: 'user', content: '要删的会话', created_at: '2026-09-20T08:00:00Z' }
      ]))
      .mockResolvedValueOnce(jsonResponse(null))
    vi.stubGlobal('fetch', fetchMock)

    await client.openConversation(31)
    await client.deleteConversation(31)

    const [url, init] = fetchMock.mock.calls[1]
    expect(String(url)).toBe('http://127.0.0.1:8000/api/v1/embed/conversations/31')
    expect((init as RequestInit).method).toBe('DELETE')
    // 删掉当前会话后不能停在一个已删除的会话上。
    expect(client.currentConversationId).toBeUndefined()
    expect(client.getMessages()).toEqual([])
  })

  it('keeps the current conversation when deleting a different one', async () => {
    const client = createClient()
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(jsonResponse([
        { id: 1, role: 'user', content: '当前会话', created_at: '2026-09-20T08:00:00Z' }
      ]))
      .mockResolvedValueOnce(jsonResponse(null)))
    await client.openConversation(31)

    await client.deleteConversation(32)

    expect(client.currentConversationId).toBe('31')
    expect(client.getMessages().length).toBe(1)
  })
})
