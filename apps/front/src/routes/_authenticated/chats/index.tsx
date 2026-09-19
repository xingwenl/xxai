import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { Chats } from '@/features/chats'

// conversation 供「任务执行记录 → 查看会话」这类外部入口直接定位会话。
const chatsSearchSchema = z.object({
  conversation: z.coerce.number().optional(),
})

export const Route = createFileRoute('/_authenticated/chats/')({
  validateSearch: chatsSearchSchema,
  component: Chats,
})
