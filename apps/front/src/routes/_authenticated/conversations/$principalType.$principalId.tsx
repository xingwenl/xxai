import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { PrincipalDetailPage } from '@/features/conversations/principal-detail-page'

const principalDetailSearch = z.object({
  platform: z.coerce.number().optional(),
  // 主体名称由上一层的链接带过来，省掉一次为了显示标题的额外请求。
  name: z.string().optional(),
})

export const Route = createFileRoute(
  '/_authenticated/conversations/$principalType/$principalId'
)({
  validateSearch: principalDetailSearch,
  component: PrincipalDetailPage,
})
