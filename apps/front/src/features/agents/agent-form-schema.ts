import { z } from 'zod'

export const agentSchema = z.object({
  name: z.string().min(1, '请输入名称').max(120),
  slug: z
    .string()
    .min(2, '标识至少 2 个字符')
    .regex(/^[a-z0-9][a-z0-9_-]*$/, '只允许小写字母、数字、下划线和短横线'),
  description: z.string().max(500).optional(),
  is_active: z.boolean(),
  /**
   * 编排工作流绑定：null = 不绑定。放进表单是为了让「读取服务端值 → 用户修改 → 提交」
   * 走同一条链路，避免用 effect 把服务端值同步进额外 state。
   */
  orchestration_workflow_id: z.number().nullable().optional(),
})

export type AgentForm = z.infer<typeof agentSchema>
