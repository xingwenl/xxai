import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { TaskDetailPage } from '@/features/tasks/task-detail-page'

const taskDetailSearch = z.object({
  platform: z.coerce.number().optional(),
  tab: z.enum(['overview', 'runs']).optional(),
})

export const Route = createFileRoute('/_authenticated/tasks/$taskId')({
  validateSearch: taskDetailSearch,
  component: TaskDetailPage,
})
