import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { TasksPage } from '@/features/tasks'

const taskSearchSchema = z.object({
  page: z.number().optional().catch(1),
  pageSize: z.number().optional().catch(20),
  status: z.enum(['active', 'paused']).optional().catch(undefined),
})

export const Route = createFileRoute('/_authenticated/tasks/')({
  validateSearch: taskSearchSchema,
  component: TasksPage,
})
