import type { AgentLoopRun, AgentLoopStep, MessageContentBlock } from '../core'

const TEXT_BLOCK_TYPES = new Set(['markdown', 'text'])

export function hasRenderableMessageContent(blocks: MessageContentBlock[]): boolean {
  return blocks.some((block) => {
    if (TEXT_BLOCK_TYPES.has(block.type)) return Boolean(block.text?.trim())
    return true
  })
}

export function loopSummaryLabel(loop: AgentLoopRun): string {
  const labels = [...new Set(loop.steps.map((step) => kindLabel(step, loop.status)))]
    .filter(Boolean)
  const prefix = loop.status === 'running' ? '思考中' : '已思考'
  return labels.length ? `${prefix} · ${labels.join(' · ')}` : prefix
}

function kindLabel(step: AgentLoopStep, status: AgentLoopRun['status']): string {
  if (step.stepType === 'knowledge_retrieval') {
    return status === 'running' ? '检索知识库' : '引用知识库'
  }
  if (step.stepType === 'skill_instruction' || step.stepType === 'skill_tool') {
    return '调用技能'
  }
  if (
    step.stepType === 'builtin_tool' ||
    step.stepType === 'host_tool' ||
    step.stepType === 'mcp_tool'
  ) {
    return '调用工具'
  }
  return ''
}
