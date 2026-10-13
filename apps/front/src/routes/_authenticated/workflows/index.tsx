import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { WorkflowsPage } from '@/features/workflows'

const workflowSearchSchema = z.object({
  page: z.number().optional().catch(1),
  pageSize: z.number().optional().catch(20),
  status: z.enum(['active', 'paused']).optional().catch(undefined),
})

export const Route = createFileRoute('/_authenticated/workflows/')({
  validateSearch: workflowSearchSchema,
  component: WorkflowsPage,
})
