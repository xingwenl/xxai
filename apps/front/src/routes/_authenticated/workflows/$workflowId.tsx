import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { WorkflowDetailPage } from '@/features/workflows/workflow-detail-page'

const workflowDetailSearch = z.object({
  platform: z.coerce.number().optional(),
  tab: z.enum(['definition', 'runs']).optional(),
})

export const Route = createFileRoute('/_authenticated/workflows/$workflowId')({
  validateSearch: workflowDetailSearch,
  component: WorkflowDetailPage,
})
