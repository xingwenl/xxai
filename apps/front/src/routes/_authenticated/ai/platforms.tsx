import { createFileRoute } from '@tanstack/react-router'
import { PlatformsPage } from '@/features/platforms'

export const Route = createFileRoute('/_authenticated/ai/platforms')({
  component: PlatformsPage,
})
