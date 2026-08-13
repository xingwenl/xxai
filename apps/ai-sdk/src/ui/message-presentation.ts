import type { AgentLoopRun, AgentLoopStep, KnowledgeCitation, MessageContentBlock } from '../core'

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

export const THINKING_PLACEHOLDER = '正在理解你的问题并组织回答...'

export function thinkingDisplayText(step: AgentLoopStep): string {
  return step.thinkingText?.trim() || step.outputSummary?.trim() || THINKING_PLACEHOLDER
}

export function isSkillStep(step: AgentLoopStep): boolean {
  return step.stepType === 'skill_instruction' || step.stepType === 'skill_tool'
}

export function leadingSkillSteps(steps: AgentLoopStep[]): AgentLoopStep[] {
  // 只合并“回答开始前”连续出现的技能步骤：按 sequence 升序扫描，遇到首个
  // model_generation 即停止；连续技能步骤之外的普通步骤（如知识库检索）不拆组，
  // 但技能组一旦被打断就不再跨过该步骤继续合并，回答中途再调用的技能保持独立卡片。
  const sorted = [...steps].sort((a, b) => a.sequence - b.sequence)
  const group: AgentLoopStep[] = []
  for (const step of sorted) {
    if (isSkillStep(step)) {
      group.push(step)
      continue
    }
    if (step.stepType === 'model_generation') break
    if (group.length) break
  }
  return group
}

export function toolInputSummary(step: AgentLoopStep): string {
  return step.inputSummary?.trim() || ''
}

export function toolOutputSummary(step: AgentLoopStep): string {
  return step.outputSummary?.trim() || ''
}

export function toolOutputDetail(step: AgentLoopStep): string {
  return toolOutputSummary(step).replace(/^工具执行(完成|失败)：/, '').trim()
}

export function toolStatusText(step: AgentLoopStep): string {
  if (step.status === 'running' || step.status === 'queued') return '正在执行...'
  if (step.status === 'waiting_confirmation') return '等待用户确认'
  if (step.status === 'failed' || step.status === 'cancelled') return '执行失败'
  return '执行完成'
}

export function citationKnowledgeBaseName(citation: KnowledgeCitation): string {
  return citation.knowledgeBase?.name?.trim() || ''
}

export function citationPassage(citation: KnowledgeCitation): string {
  return citation.text?.trim() || ''
}

export function citationTitle(citation: KnowledgeCitation, index: number): string {
  return String(citation.title?.trim() || `来源 ${index + 1}`)
}

export function citationSourceText(citation: KnowledgeCitation): string {
  return String(
    citation.sourceUrl ||
    citation.source ||
    citationKnowledgeBaseName(citation) ||
    '知识库引用'
  )
}

export function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength)}…`
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
