import { describe, expect, it } from 'vitest'
import { mapHistoryMessage, mapHistoryMessages } from '../map-history'

describe('mapHistoryMessage 的用量透传', () => {
  it('快照带 usage 时写进 metadata.usage，形状与实时事件一致', () => {
    const message = mapHistoryMessage(
      {
        id: 7,
        role: 'assistant',
        content: '回答',
        usage: {
          prompt_tokens: 120,
          completion_tokens: 8,
          total_tokens: 128,
          cache_read_tokens: 90,
          model: 'deepseek-v4-pro',
          provider: 'deepseek'
        }
      },
      'conv-1'
    )

    expect(message.metadata).toEqual({
      usage: {
        prompt_tokens: 120,
        completion_tokens: 8,
        total_tokens: 128,
        cache_read_tokens: 90,
        model: 'deepseek-v4-pro',
        provider: 'deepseek'
      }
    })
  })

  it('存量消息没有 usage 时 metadata 缺省，不塞空对象', () => {
    expect(mapHistoryMessage({ id: 1, role: 'assistant', content: '旧消息' }, 'conv-1').metadata)
      .toBeUndefined()
    expect(
      mapHistoryMessage({ id: 2, role: 'assistant', content: '空对象', usage: {} }, 'conv-1')
        .metadata
    ).toBeUndefined()
  })

  it('数组映射对每条消息独立生效', () => {
    const messages = mapHistoryMessages(
      [
        { id: 1, role: 'user', content: '问题' },
        { id: 2, role: 'assistant', content: '回答', usage: { prompt_tokens: 1, completion_tokens: 1 } }
      ],
      'conv-1'
    )

    expect(messages[0].metadata).toBeUndefined()
    expect(messages[1].metadata).toEqual({ usage: { prompt_tokens: 1, completion_tokens: 1 } })
  })
})
