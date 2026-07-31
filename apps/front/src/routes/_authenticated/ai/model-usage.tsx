import { createFileRoute } from '@tanstack/react-router'
import { ModelUsagePage } from '@/features/model-usage'

export const Route = createFileRoute('/_authenticated/ai/model-usage')({
  component: ModelUsagePage,
})
