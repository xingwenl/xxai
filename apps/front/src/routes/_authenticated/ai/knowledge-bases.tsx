import { createFileRoute } from '@tanstack/react-router'
import { KnowledgeBasesPage } from '@/features/knowledge'

export const Route = createFileRoute('/_authenticated/ai/knowledge-bases')({
  component: KnowledgeBasesPage,
})
