import z from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { AiHtmlPagesPage } from '@/features/system/ai-html-pages'

const aiHtmlPagesSearchSchema = z.object({
  page: z.number().optional().catch(1),
  pageSize: z.number().optional().catch(10),
  title: z.string().optional().catch(''),
})

export const Route = createFileRoute('/_authenticated/system/ai-html-pages')({
  validateSearch: aiHtmlPagesSearchSchema,
  component: AiHtmlPagesRoute,
})

function AiHtmlPagesRoute() {
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  return <AiHtmlPagesPage search={search} navigate={navigate} />
}
