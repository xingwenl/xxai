import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  buildSelectionStorageKey,
  classifyTokenFailure,
  clearSelectedAgent,
  deriveAgentEndpoint,
  findAgentOption,
  formatAgentSwitchError,
  isValidAgentOption,
  normalizeAgentId,
  readSelectedAgent,
  resolveAgentSwitchingOptions,
  writeSelectedAgent
} from '../agent-switching'

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

describe('resolveAgentSwitchingOptions', () => {
  it('drops options without a usable agentId or a non-empty name', () => {
    const resolved = resolveAgentSwitchingOptions({
      agents: [
        { agentId: '1', name: '客服助手' },
        { agentId: 2, name: '数据分析' },
        { agentId: '', name: '空 id' },
        { agentId: '3', name: '   ' },
        // 宿主传回后台 detail 字段时的容错：缺少 name 不算候选。
        { agentId: '4' } as never
      ]
    })

    expect(resolved.agents.map((option) => option.agentId)).toEqual(['1', 2])
    expect(resolved.enabled).toBe(true)
  })

  it('keeps the local kill switch: explicit enabled=false hides everything', () => {
    const resolved = resolveAgentSwitchingOptions({
      enabled: false,
      agents: [{ agentId: '1', name: '客服助手' }]
    })

    expect(resolved.agents).toHaveLength(1)
    expect(resolved.enabled).toBe(false)
  })

  it('treats a missing configuration as "no candidates" rather than throwing', () => {
    expect(resolveAgentSwitchingOptions(undefined)).toEqual({
      agents: [],
      enabled: true
    })
  })
})

describe('agent id helpers', () => {
  it('normalizes number and string ids to the same lookup key', () => {
    expect(normalizeAgentId(2)).toBe('2')
    const agents = [{ agentId: 2, name: '数据分析' }]
    expect(findAgentOption(agents, '2')?.name).toBe('数据分析')
    expect(findAgentOption(agents, '3')).toBeUndefined()
  })

  it('keeps the selection key scoped by platform and end user', () => {
    expect(buildSelectionStorageKey('p', 'u1')).toBe(
      'xxai-agent:selected-agent:p:u1'
    )
    // 匿名用户与消息存储使用同一个 anonymous 约定。
    expect(buildSelectionStorageKey('p', undefined)).toBe(
      'xxai-agent:selected-agent:p:anonymous'
    )
  })

  it('round-trips the remembered agent and degrades when storage is unavailable', () => {
    stubStorage()
    const key = buildSelectionStorageKey('p', 'u1')

    writeSelectedAgent(key, '2')
    expect(readSelectedAgent(key)).toBe('2')

    clearSelectedAgent(key)
    expect(readSelectedAgent(key)).toBeNull()

    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('blocked')
      },
      setItem: () => {
        throw new Error('quota')
      },
      removeItem: () => {
        throw new Error('blocked')
      }
    })
    expect(readSelectedAgent(key)).toBeNull()
    // 写入/清除失败只降级，不向调用方抛错。
    expect(() => writeSelectedAgent(key, '2')).not.toThrow()
    expect(() => clearSelectedAgent(key)).not.toThrow()
  })
})

describe('deriveAgentEndpoint', () => {
  it('replaces the agent id segment and keeps the rest of the endpoint intact', () => {
    expect(
      deriveAgentEndpoint(
        'wss://api.example.com/api/v1/ws/agents/1?trace=on',
        '2'
      )
    ).toBe('wss://api.example.com/api/v1/ws/agents/2?trace=on')
  })

  it('returns null for custom endpoints without a /ws/agents/{id} segment', () => {
    expect(deriveAgentEndpoint('wss://api.example.com/custom/agent', '2')).toBeNull()
    expect(deriveAgentEndpoint('', '2')).toBeNull()
  })
})

describe('classifyTokenFailure', () => {
  it('maps HTTP auth and quota statuses to actionable reasons', () => {
    expect(classifyTokenFailure({ response: { status: 401 } })).toBe('not_bound')
    expect(classifyTokenFailure({ response: { status: 403 } })).toBe('not_bound')
    expect(classifyTokenFailure({ response: { status: 429 } })).toBe('quota')
    expect(classifyTokenFailure({ response: { status: 500 } })).toBe('network')
  })

  it('falls back to the error code when the host throws an SDK error', () => {
    expect(classifyTokenFailure({ code: 'embed_agent_not_allowed' })).toBe('network')
    expect(classifyTokenFailure({ code: 'unauthorized' })).toBe('not_bound')
    expect(classifyTokenFailure({ code: 'forbidden' })).toBe('not_bound')
    expect(classifyTokenFailure(undefined)).toBe('network')
  })
})

describe('formatAgentSwitchError', () => {
  it('distinguishes permission failures from transient failures', () => {
    expect(formatAgentSwitchError('not_bound')).toBe('该智能体未授权给当前接入方')
    expect(formatAgentSwitchError('not_allowed')).toBe('当前接入未开启智能体切换')
    expect(formatAgentSwitchError('busy')).toBe('正在生成回答，请稍后再切换')
    expect(formatAgentSwitchError('connection_failed')).toBe(
      '已切换智能体，但连接失败，请重试'
    )
    expect(formatAgentSwitchError('network')).toContain('网络')
  })
})

describe('isValidAgentOption', () => {
  it('rejects primitives and non-finite numeric ids', () => {
    expect(isValidAgentOption(null)).toBe(false)
    expect(isValidAgentOption('1')).toBe(false)
    expect(isValidAgentOption({ agentId: Number.NaN, name: 'a' })).toBe(false)
    expect(isValidAgentOption({ agentId: '1', name: 'a' })).toBe(true)
  })
})
