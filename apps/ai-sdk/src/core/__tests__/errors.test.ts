import { describe, expect, it } from 'vitest'
import { agentError, agentErrorFromResponse, isAgentError } from '../errors'

describe('agentError', () => {
  it('preserves code, retryable, requestId and details from a payload', () => {
    const error = agentError({
      code: 'chat_model_unavailable',
      message: '对话模型不可用',
      retryable: false,
      requestId: 'req-9',
      details: { modelId: 3 }
    })

    expect(error).toBeInstanceOf(Error)
    expect(isAgentError(error)).toBe(true)
    expect(error.message).toBe('对话模型不可用')
    expect(error.code).toBe('chat_model_unavailable')
    expect(error.retryable).toBe(false)
    expect(error.requestId).toBe('req-9')
    expect(error.details).toEqual({ modelId: 3 })
  })

  it('falls back to the code when the payload has no message', () => {
    expect(agentError({ code: 'request_in_progress' }).message).toBe('request_in_progress')
  })

  it('uses the fallback text for a non-object payload', () => {
    const error = agentError(undefined, '请求失败')

    expect(error.message).toBe('请求失败')
    expect(error.code).toBeUndefined()
  })

  it('normalises an existing Error in place without losing identity', () => {
    const original = new Error('boom') as Error & { code?: string }
    const normalised = agentError(original)

    expect(normalised).toBe(original)
    expect(isAgentError(original)).toBe(true)
  })

  it('is idempotent', () => {
    const once = agentError({ code: 'a', retryable: true })

    expect(agentError(once)).toBe(once)
  })
})

describe('agentErrorFromResponse', () => {
  const response = (status: number, body: unknown) => ({
    status,
    json: async () => body
  })

  it('reads the business code from error_code, not the numeric code', async () => {
    const error = await agentErrorFromResponse(
      response(409, { code: 409, error_code: 'chat_model_unavailable', message: '对话模型不可用' }),
      '请求失败'
    )

    expect(error.code).toBe('chat_model_unavailable')
    expect(error.message).toBe('对话模型不可用')
    expect(error.retryable).toBe(false)
  })

  it('marks 5xx and 429 as retryable', async () => {
    expect((await agentErrorFromResponse(response(503, {}), 'x')).retryable).toBe(true)
    expect((await agentErrorFromResponse(response(429, {}), 'x')).retryable).toBe(true)
    expect((await agentErrorFromResponse(response(400, {}), 'x')).retryable).toBe(false)
  })

  it('keeps the status in the message and falls back to a status-derived code', async () => {
    const error = await agentErrorFromResponse(
      { status: 502, json: async () => { throw new Error('not json') } },
      '会话列表加载失败'
    )

    expect(error.message).toBe('会话列表加载失败: 502')
    expect(error.code).toBe('http_502')
  })
})
