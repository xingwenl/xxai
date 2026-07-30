import { createFileRoute } from '@tanstack/react-router'
import { EmbedClientsPage } from '@/features/embed-clients'

export const Route = createFileRoute('/_authenticated/ai/embed-clients')({
  component: EmbedClientsPage,
})
