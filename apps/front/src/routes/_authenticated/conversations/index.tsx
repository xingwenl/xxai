import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { ConversationsPage } from '@/features/conversations'

const conversationsSearch = z.object({
  platform: z.coerce.number().optional(),
})

export const Route = createFileRoute('/_authenticated/conversations/')({
  validateSearch: conversationsSearch,
  component: ConversationsRouteComponent,
})

function ConversationsRouteComponent() {
  const search = Route.useSearch()
  return <ConversationsPage initialPlatformId={search.platform} />
}
