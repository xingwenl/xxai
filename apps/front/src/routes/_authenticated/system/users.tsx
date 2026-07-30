import z from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { SystemUsersPage } from '@/features/system/users'

const systemUsersSearchSchema = z.object({
  page: z.number().optional().catch(1),
  pageSize: z.number().optional().catch(10),
  name: z.string().optional().catch(''),
  email: z.string().optional().catch(''),
})

export const Route = createFileRoute('/_authenticated/system/users')({
  validateSearch: systemUsersSearchSchema,
  component: SystemUsersRoute,
})

function SystemUsersRoute() {
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  return <SystemUsersPage search={search} navigate={navigate} />
}
