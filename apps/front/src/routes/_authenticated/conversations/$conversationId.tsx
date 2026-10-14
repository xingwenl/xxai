import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { ConversationDetailPage } from '@/features/conversations/conversation-detail-page'

const conversationDetailSearch = z.object({
  platform: z.coerce.number().optional(),
})

export const Route = createFileRoute(
  '/_authenticated/conversations/$conversationId'
)({
  validateSearch: conversationDetailSearch,
  component: ConversationDetailPage,
})
