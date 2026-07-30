import { createFileRoute } from '@tanstack/react-router'
import { AgentsPage } from '@/features/agents'

export const Route = createFileRoute('/_authenticated/ai/bots')({
  component: AgentsPage,
})
