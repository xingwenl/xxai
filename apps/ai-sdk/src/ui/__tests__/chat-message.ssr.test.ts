// @vitest-environment jsdom
// 默认关闭过程卡片后需要断言「正文仍渲染」，这会真正走一遍 MarkdownContent，
// 而 DOMPurify v3 依赖 window；node 环境下 sanitize 不可用，故切到 jsdom。
import { describe, expect, it } from 'vitest'
import { createSSRApp, h, type Component } from 'vue'
import { renderToString } from '@vue/server-renderer'
import type { AgentLoopStep, Message } from '../../core'
import ChatMessage from '../components/ChatMessage.vue'
import AgentLoopPanel from '../components/AgentLoopPanel.vue'

function step(
  id: string,
  stepType: string,
  sequence: number,
  extra: Partial<AgentLoopStep> = {},
): AgentLoopStep {
  return {
    id,
    sequence,
    stepType,
    title: id,
    status: 'succeeded',
    ...extra,
  }
}

const loopSteps: AgentLoopStep[] = [
  step('kb', 'knowledge_retrieval', 1, { outputSummary: '命中 2 条引用' }),
  step('si', 'skill_instruction', 2, {
    skillName: 'ai-video-script',
    skillVersion: '1.2.0',
    outputSummary: '技能元数据已加载，可调用脚本工具',
  }),
  step('st', 'skill_tool', 3, {
    skillName: 'ai-video-script',
    skillVersion: '1.2.0',
    outputSummary: '技能执行完成：{"ok":true}',
  }),
  step('gen', 'model_generation', 4, {
    thinkingText: '好的，我先分析需求，再组织回答。',
    outputSummary: '生成 16 字符',
  }),
]

function message(overrides: Partial<Message> = {}): Message {
  return {
    id: 'm1',
    role: 'assistant',
    type: 'text',
    content: { type: 'text', text: '最终回答' },
    timeline: [
      { kind: 'step', id: 't1', stepId: 'kb' },
      { kind: 'step', id: 't2', stepId: 'si' },
      { kind: 'step', id: 't3', stepId: 'st' },
      { kind: 'step', id: 't4', stepId: 'gen' },
    ],
    loop: {
      id: 'loop-1',
      requestId: 'request-1',
      status: 'completed',
      steps: loopSteps,
    },
    timestamp: new Date(),
    ...overrides,
  }
}

async function render(component: Component, props: Record<string, unknown>): Promise<string> {
  const app = createSSRApp({ render: () => h(component, props) })
  return renderToString(app)
}

describe('ChatMessage timeline rendering', () => {
  it('renders rich content blocks (custom) even when timeline exists', async () => {
    const html = await render(ChatMessage, {
      message: message({
        contentBlocks: [
          {
            id: 'c1',
            type: 'custom',
            status: 'completed',
            component_name: 'UserInfoCard',
            props: { name: '张三' },
            fallback: '张三 · zhangsan@example.com',
          },
        ],
      }),
    })

    expect(html).toContain('张三 · zhangsan@example.com')
  })

  it('merges leading skill steps into one collapsible group', async () => {
    const html = await render(ChatMessage, {
      message: message(),
      showAgentSteps: true,
    })

    expect(html).toContain('调用技能 · 2 个')
    expect(html.match(/class="xxai-loop-skill-item"/g)?.length).toBe(2)
    expect(html.match(/ai-video-script/g)?.length).toBe(2)
    expect(html).toContain('技能元数据已加载，可调用脚本工具')
    expect(html).toContain('技能执行完成')
    expect(html).toContain('思考过程（16 字）')
    expect(html).toContain('好的，我先分析需求，再组织回答。')
  })

  it('renders thinking as a collapsed details after completion', async () => {
    const html = await render(ChatMessage, {
      message: message(),
      showAgentSteps: true,
    })

    expect(html).toMatch(/<details class="xxai-loop-collapse"[^>]*>/)
    expect(html).not.toMatch(/<details class="xxai-loop-collapse"[^>]*open/)
  })

  it('keeps thinking details open while generation is running', async () => {
    const running = loopSteps.map((item) =>
      item.id === 'gen' ? { ...item, status: 'running' as const } : item,
    )
    const html = await render(ChatMessage, {
      message: message({
        loop: { ...message().loop!, status: 'running', steps: running },
      }),
      showAgentSteps: true,
    })

    expect(html).toContain('<details class="xxai-loop-collapse" open')
  })

  it('does not merge skills that appear after generation', async () => {
    const steps = [
      step('gen', 'model_generation', 1, { thinkingText: '先回答' }),
      step('st', 'skill_tool', 2, {
        skillName: 'ai-video-script',
        outputSummary: '回答中途再次调用',
      }),
    ]
    const html = await render(ChatMessage, {
      message: message({
        timeline: [
          { kind: 'step', id: 't1', stepId: 'gen' },
          { kind: 'step', id: 't2', stepId: 'st' },
        ],
        loop: { ...message().loop!, steps },
      }),
      showAgentSteps: true,
    })

    expect(html).not.toContain('调用技能 ·')
    expect(html).toContain('回答中途再次调用')
  })
})

describe('ChatMessage hides agent steps by default', () => {
  it('renders only the answer text when showAgentSteps is not passed', async () => {
    const html = await render(ChatMessage, { message: message() })

    expect(html).not.toContain('xxai-loop-card')
    expect(html).not.toContain('xxai-loop-skill-group')
    expect(html).not.toContain('xxai-agent-loop')
    expect(html).not.toContain('思考过程（')
    expect(html).toContain('最终回答')
  })

  it('keeps timeline answer text while dropping step entries', async () => {
    const html = await render(ChatMessage, {
      message: message({
        timeline: [
          { kind: 'step', id: 't1', stepId: 'kb' },
          { kind: 'text', id: 't2', text: '第一段回答' },
          { kind: 'step', id: 't3', stepId: 'gen' },
          { kind: 'text', id: 't4', text: '第二段回答' },
        ],
      }),
    })

    expect(html).not.toContain('xxai-loop-card')
    expect(html).toContain('第一段回答')
    expect(html).toContain('第二段回答')
  })

  it('still shows the typing indicator for an empty pending message with a loop', async () => {
    const html = await render(ChatMessage, {
      message: message({
        // 正文为空的流式占位消息：此时不应因为丢弃过程卡片而变成完全空白。
        contentBlocks: [{ id: 'empty', type: 'markdown', text: '', status: 'streaming' }],
        timeline: undefined,
        content: { type: 'text', text: '' },
      }),
      pending: true,
    })

    expect(html).toContain('xxai-typing-indicator')
    expect(html).not.toContain('xxai-agent-loop')
  })
})

describe('AgentLoopPanel fallback rendering', () => {
  it('merges leading skill steps in the history fallback path', async () => {
    const html = await render(AgentLoopPanel, {
      message: message({
        timeline: undefined,
        loop: {
          ...message().loop!,
          status: 'running',
        },
      }),
    })

    expect(html).toContain('调用技能 · 2 个')
    expect(html).toContain('思考过程（16 字）')
  })
})
