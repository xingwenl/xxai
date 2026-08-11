import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { ModelUsagePage } from '@/features/model-usage'

const modelUsageSearch = z.object({
  platform: z.coerce.number().optional(),
  agent: z.coerce.number().optional(),
})

export const Route = createFileRoute('/_authenticated/ai/model-usage')({
  validateSearch: modelUsageSearch,
  component: ModelUsageRouteComponent,
})

function ModelUsageRouteComponent() {
  const search = Route.useSearch()
  return (
    <ModelUsagePage
      initialPlatformId={search.platform}
      initialAgentId={search.agent == null ? undefined : String(search.agent)}
    />
  )
}
