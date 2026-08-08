import { describe, expect, it } from 'vitest'
import { createPageTools } from '../page/tools'

describe('page tools', () => {
  it('exposes the six page tools with constrained schemas', () => {
    const tools = createPageTools()
    expect(tools.map(tool => tool.name)).toEqual([
      'page_snapshot', 'page_click', 'page_type', 'page_scroll', 'page_wait', 'page_extract'
    ])
    expect(tools.find(tool => tool.name === 'page_click')?.sideEffect).toBe('navigation')
    expect(tools.find(tool => tool.name === 'page_snapshot')?.inputSchema).toMatchObject({
      type: 'object',
      additionalProperties: false
    })
  })

  it('does not expose executable functions in registration metadata', () => {
    const tools = createPageTools()
    for (const tool of tools) {
      expect(tool.execute).toBeTypeOf('function')
      expect(JSON.stringify({ name: tool.name, description: tool.description, inputSchema: tool.inputSchema })).not.toContain('function')
    }
  })
})
