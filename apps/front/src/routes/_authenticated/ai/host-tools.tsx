import { createFileRoute } from '@tanstack/react-router'
import { HostToolsPage } from '@/features/host-tools'

export const Route = createFileRoute('/_authenticated/ai/host-tools')({
  component: HostToolsPage,
})
