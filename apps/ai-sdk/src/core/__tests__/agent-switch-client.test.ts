import { afterEach, describe, expect, it, vi } from 'vitest'
import { AgentClient } from '../client'
import type { AgentClientOptions } from '../types'

afterEach(() => {
  vi.unstubAllGlobals()
})

function stubStorage() {
  const store = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => store.set(key, String(value)),
    removeItem: (key: string) => store.delete(key)
  })
  return store
}

function createClient(overrides: Partial<AgentClientOptions> = {}) {
  const getToken = vi.fn(async () => 'token')
  const client = new AgentClient({
    endpoint: 'ws://127.0.0.1:8000/api/v1/ws/agents/1',
    platformId: 'p',
    agentId: '1',
    getToken,
    agentSwitching: {
      agents: [
        { agentId: '1', name: '客服助手' },
        { agentId: '2', name: '数据分析' }
      ]
    },
    ...overrides
  })
  return { client, getToken }
}

describe('AgentClient agent switching', () => {
  it('switches token target, storage key and restores the target agent conversation', async () => {
    const store = stubStorage()
    store.set(
      'xxai-agent:p:2:anonymous',
      JSON.stringify({
        version: 1,
        conversationId: '222',
        messages: [
          {
            id: 'm1',
            role: 'user',
            content: 'hi',
            timestamp: new Date().toISOString()
          }
        ]
      })
    )
    const { client, getToken } = createClient()
    ;(client as any)._clientInfo = { allowAgentSwitching: true }
    const switched = vi.fn()
    client.on('agent_switched', switched)

    expect(client.showAgentSwitcher).toBe(true)
    expect(await client.switchAgent('2')).toBe(true)

    expect(client.currentAgentId).toBe('2')
    expect(client.storageKey).toBe('xxai-agent:p:2:anonymous')
    // 切换时必须以目标 agent 换 token，否则服务端会按旧的 agent_id 签发。
    expect(getToken).toHaveBeenCalledWith(
      expect.objectContaining({ platformId: 'p', agentId: '2' })
    )
    expect(switched).toHaveBeenCalledWith(
      expect.objectContaining({
        agentId: '2',
        previousAgentId: '1',
        conversationId: '222',
        restored: true
      })
    )
  })

  it('keeps the current agent and connection state when the target token is rejected', async () => {
    stubStorage()
    const { client } = createClient({
      getToken: vi.fn(async (ctx) => {
        if (String(ctx.agentId) === '2') throw { response: { status: 403 } }
        return 'token'
      })
    })
    ;(client as any)._clientInfo = { allowAgentSwitching: true }
    const failed = vi.fn()
    const switched = vi.fn()
    client.on('agent_switch_failed', failed)
    client.on('agent_switched', switched)

    expect(await client.switchAgent('2')).toBe(false)

    // 两阶段切换：预签失败时什么都没改，UI 仍停留在原 agent 的会话上。
    expect(client.currentAgentId).toBe('1')
    expect(client.storageKey).toBe('xxai-agent:p:1:anonymous')
    expect(switched).not.toHaveBeenCalled()
    expect(failed).toHaveBeenCalledWith(
      expect.objectContaining({
        agentId: '2',
        previousAgentId: '1',
        reason: 'not_bound'
      })
    )
  })

  it('refuses to switch when the backend policy is off, even with candidates configured', async () => {
    stubStorage()
    const { client, getToken } = createClient()
    const failed = vi.fn()
    client.on('agent_switch_failed', failed)

    // 未抵达 session_ready 时策略未知，按关闭处理（fail closed）。
    expect(client.showAgentSwitcher).toBe(false)
    expect(client.availableAgents).toEqual([])
    expect(await client.switchAgent('2')).toBe(false)
    expect(getToken).not.toHaveBeenCalled()
    expect(failed).toHaveBeenCalledWith(
      expect.objectContaining({ reason: 'not_allowed' })
    )
  })

  it('refuses to switch while a request is in flight', async () => {
    stubStorage()
    const { client } = createClient()
    ;(client as any)._clientInfo = { allowAgentSwitching: true }
    ;(client as any).activeRequestId = 'request-1'
    const failed = vi.fn()
    client.on('agent_switch_failed', failed)

    expect(client.canSwitchAgent).toBe(false)
    expect(await client.switchAgent('2')).toBe(false)
    expect(failed).toHaveBeenCalledWith(
      expect.objectContaining({ reason: 'busy' })
    )
  })

  it('refuses to switch when the endpoint cannot carry a per-agent path', async () => {
    stubStorage()
    const { client } = createClient({
      endpoint: 'ws://127.0.0.1:8000/custom/gateway'
    })
    ;(client as any)._clientInfo = { allowAgentSwitching: true }
    const failed = vi.fn()
    client.on('agent_switch_failed', failed)

    expect(await client.switchAgent('2')).toBe(false)
    expect(failed).toHaveBeenCalledWith(
      expect.objectContaining({ reason: 'not_supported' })
    )
  })

  it('rejects targets that are not in the host-provided candidate list', async () => {
    stubStorage()
    const { client, getToken } = createClient()
    ;(client as any)._clientInfo = { allowAgentSwitching: true }
    const failed = vi.fn()
    client.on('agent_switch_failed', failed)

    expect(await client.switchAgent('99')).toBe(false)
    expect(getToken).not.toHaveBeenCalled()
    expect(failed).toHaveBeenCalledWith(
      expect.objectContaining({ reason: 'not_allowed' })
    )
  })

  it('connects the remembered agent first when one was selected before', () => {
    stubStorage()
    ;(globalThis.localStorage as Storage).setItem(
      'xxai-agent:selected-agent:p:anonymous',
      '2'
    )
    const { client } = createClient()

    expect(client.currentAgentId).toBe('2')
    expect(client.storageKey).toBe('xxai-agent:p:2:anonymous')
  })

  it('falls back to the configured agent when the remembered one is not a candidate', () => {
    stubStorage()
    ;(globalThis.localStorage as Storage).setItem(
      'xxai-agent:selected-agent:p:anonymous',
      '99'
    )
    const { client } = createClient()

    expect(client.currentAgentId).toBe('1')
  })

  it('clears the remembered selection and rolls back to the configured agent when the first session disables switching', async () => {
    stubStorage()
    ;(globalThis.localStorage as Storage).setItem(
      'xxai-agent:selected-agent:p:anonymous',
      '2'
    )
    const { client } = createClient()
    ;(client as any)._clientInfo = { allowAgentSwitching: false }

    ;(client as any)._reconcileAgentSwitchingPolicy()
    // 回退是异步的：等微任务队列里的 token 预签与重建走完。
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(client.currentAgentId).toBe('1')
    expect(
      (globalThis.localStorage as Storage).getItem(
        'xxai-agent:selected-agent:p:anonymous'
      )
    ).toBeNull()
  })
})
