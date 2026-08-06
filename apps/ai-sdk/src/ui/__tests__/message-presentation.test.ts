import { describe, expect, it } from 'vitest'
import type { AgentLoopRun, MessageContentBlock } from '../../core'
import {
  hasRenderableMessageContent,
  loopSummaryLabel
} from '../message-presentation'

describe('message presentation', () => {
  it('hides empty text blocks but keeps non-text content', () => {
    expect(hasRenderableMessageContent([])).toBe(false)
    expect(hasRenderableMessageContent([
      { id: 'empty', type: 'markdown', text: '  \n ' }
    ])).toBe(false)
    expect(hasRenderableMessageContent([
      { id: 'file', type: 'file', fileName: 'report.pdf' }
    ])).toBe(true)
  })

  it('describes live tool and knowledge steps before completion', () => {
    const loop: AgentLoopRun = {
      id: 'loop-1',
      requestId: 'request-1',
      status: 'running',
      steps: [
        step('thinking', 'model_generation', 1),
        step('tool', 'mcp_tool', 2),
        step('knowledge', 'knowledge_retrieval', 3)
      ]
    }

    expect(loopSummaryLabel(loop)).toBe('思考中 · 调用工具 · 检索知识库')
    expect(loopSummaryLabel({ ...loop, steps: [] })).toBe('思考中')
    expect(loopSummaryLabel({ ...loop, status: 'completed' })).toBe(
      '已思考 · 调用工具 · 引用知识库'
    )
  })
})

function step(id: string, stepType: string, sequence: number) {
  return {
    id,
    sequence,
    stepType,
    title: id,
    status: 'running' as const
  }
}
