import { z } from 'zod'

export const agentSchema = z.object({
  name: z.string().min(1, '请输入名称').max(120),
  slug: z
    .string()
    .min(2, '标识至少 2 个字符')
    .regex(/^[a-z0-9][a-z0-9_-]*$/, '只允许小写字母、数字、下划线和短横线'),
  description: z.string().max(500).optional(),
  is_active: z.boolean(),
})

export type AgentForm = z.infer<typeof agentSchema>
