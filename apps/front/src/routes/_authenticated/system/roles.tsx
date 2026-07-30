import z from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { SystemRolesPage } from '@/features/system/roles'

const systemRolesSearchSchema = z.object({
  page: z.number().optional().catch(1),
  pageSize: z.number().optional().catch(10),
  name: z.string().optional().catch(''),
  code: z.string().optional().catch(''),
})

export const Route = createFileRoute('/_authenticated/system/roles')({
  validateSearch: systemRolesSearchSchema,
  component: SystemRolesRoute,
})

function SystemRolesRoute() {
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  return <SystemRolesPage search={search} navigate={navigate} />
}
