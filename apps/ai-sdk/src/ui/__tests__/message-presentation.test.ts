import { describe, expect, it } from 'vitest'
import type { AgentLoopRun, MessageContentBlock } from '../../core'
import {
  hasRenderableMessageContent,
  isSkillStep,
  leadingSkillSteps,
  loopSummaryLabel,
  thinkingDisplayText,
  toolInputSummary,
  toolOutputDetail,
  toolStatusText,
  citationKnowledgeBaseName,
  citationPassage,
  citationTitle,
  truncateText,
  THINKING_PLACEHOLDER
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
        step('builtin', 'builtin_tool', 3),
        step('knowledge', 'knowledge_retrieval', 4)
      ]
    }

    expect(loopSummaryLabel(loop)).toBe('思考中 · 调用工具 · 检索知识库')
    expect(loopSummaryLabel({ ...loop, steps: [] })).toBe('思考中')
    expect(loopSummaryLabel({ ...loop, status: 'completed' })).toBe(
      '已思考 · 调用工具 · 引用知识库'
    )
  })

  it('prefers streamed thinking text over summaries and placeholders', () => {
    expect(thinkingDisplayText({ ...step('s', 'model_generation', 1), thinkingText: ' 先分析 ' }))
      .toBe('先分析')
    expect(thinkingDisplayText({ ...step('s', 'model_generation', 1), outputSummary: '生成 4 字符' }))
      .toBe('生成 4 字符')
    expect(thinkingDisplayText(step('s', 'model_generation', 1))).toBe(THINKING_PLACEHOLDER)
  })

  it('splits tool input and output details for display', () => {
    const toolStep = {
      ...step('t', 'mcp_tool', 2),
      inputSummary: '{"city":"上海"}',
      outputSummary: '工具执行完成：{"weather":"晴"}'
    }
    expect(toolInputSummary(toolStep)).toBe('{"city":"上海"}')
    expect(toolOutputDetail(toolStep)).toBe('{"weather":"晴"}')
    expect(toolStatusText({ ...toolStep, status: 'succeeded' })).toBe('执行完成')
    expect(toolStatusText({ ...toolStep, status: 'waiting_confirmation' })).toBe('等待用户确认')
    expect(toolStatusText({ ...toolStep, status: 'running' })).toBe('正在执行...')
  })

  it('exposes knowledge base name and passage from citations', () => {
    const citation = {
      title: '退款规则',
      text: '七天无理由退款',
      knowledgeBase: { id: 3, name: '客服知识库', slug: 'support' }
    }
    expect(citationKnowledgeBaseName(citation)).toBe('客服知识库')
    expect(citationPassage(citation)).toBe('七天无理由退款')
    expect(citationTitle(citation, 0)).toBe('退款规则')
    expect(citationTitle({ title: ' ' }, 2)).toBe('来源 3')
  })

  it('truncates long text with an ellipsis', () => {
    expect(truncateText('abcdef', 4)).toBe('abcd…')
    expect(truncateText('abc', 4)).toBe('abc')
  })

  it('merges consecutive leading skill steps before generation', () => {
    const steps = [
      step('kb', 'knowledge_retrieval', 1),
      step('si', 'skill_instruction', 2),
      step('st', 'skill_tool', 3),
      step('gen', 'model_generation', 4),
      step('st2', 'skill_tool', 5),
    ]

    expect(leadingSkillSteps(steps).map((item) => item.id)).toEqual(['si', 'st'])
  })

  it('keeps middle-of-answer skills as independent cards', () => {
    const steps = [
      step('si', 'skill_instruction', 2),
      step('tool', 'mcp_tool', 3),
      step('si2', 'skill_instruction', 4),
      step('gen', 'model_generation', 5),
    ]

    expect(leadingSkillSteps(steps).map((item) => item.id)).toEqual(['si'])
  })

  it('returns empty group without leading skills', () => {
    expect(leadingSkillSteps([
      step('kb', 'knowledge_retrieval', 1),
      step('gen', 'model_generation', 2),
    ])).toEqual([])
    expect(leadingSkillSteps([
      step('gen', 'model_generation', 1),
      step('st', 'skill_tool', 2),
    ])).toEqual([])
    expect(leadingSkillSteps([])).toEqual([])
  })

  it('sorts group members by sequence and recognizes skill steps', () => {
    const steps = [
      step('st', 'skill_tool', 3),
      step('si', 'skill_instruction', 2),
      step('gen', 'model_generation', 4),
    ]

    expect(leadingSkillSteps(steps).map((item) => item.id)).toEqual(['si', 'st'])
    expect(isSkillStep(steps[0])).toBe(true)
    expect(isSkillStep(step('t', 'mcp_tool', 1))).toBe(false)
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
