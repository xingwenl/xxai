import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { AgentDetailPage } from '@/features/agents/agent-detail-page'

const agentDetailSearch = z.object({
  platform: z.coerce.number().optional(),
  tab: z
    .enum([
      'overview',
      'config',
      'knowledge',
      'skills',
      'tools',
      'versions',
      'usage',
    ])
    .optional(),
})

export const Route = createFileRoute('/_authenticated/ai/bots/$agentId')({
  validateSearch: agentDetailSearch,
  component: AgentDetailPage,
})
