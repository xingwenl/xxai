import { createFileRoute } from '@tanstack/react-router'
import { MyMemoryPage } from '@/features/my-memory'

export const Route = createFileRoute('/_authenticated/ai/my-memory')({
  component: MyMemoryPage,
})
