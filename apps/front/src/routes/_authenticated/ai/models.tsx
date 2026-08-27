import { createFileRoute } from '@tanstack/react-router'
import { ModelRegistryPage } from '@/features/model-registry'

export const Route = createFileRoute('/_authenticated/ai/models')({
  component: ModelRegistryPage,
})
