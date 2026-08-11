import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Wrench } from 'lucide-react'
import { toast } from 'sonner'
import {
  listAgentBuiltinTools,
  updateAgentBuiltinTool,
  type AgentBuiltinTool,
} from '@/api/builtin-tools'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'

export function BuiltinToolsSection({
  platformId,
  agentId,
}: {
  platformId?: number
  agentId: number
}) {
  const queryClient = useQueryClient()
  const queryKey = ['agent-builtin-tools', platformId, agentId] as const
  const toolsQuery = useQuery({
    queryKey,
    queryFn: () => listAgentBuiltinTools(platformId!, agentId),
    enabled: platformId != null,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey }),
      queryClient.invalidateQueries({
        queryKey: ['agent', platformId, agentId],
      }),
    ])
  }
  const updateMutation = useMutation({
    mutationFn: (tool: AgentBuiltinTool) =>
      updateAgentBuiltinTool(platformId!, agentId, tool.name, !tool.is_enabled),
    onSuccess: async () => {
      toast.success('内置工具状态已更新')
      await invalidate()
    },
    onError: () => toast.error('工具状态更新失败'),
  })

  return (
    <div className='space-y-3'>
      <p className='text-sm text-muted-foreground'>
        启用后，智能体可在下一轮对话中调用对应工具。
      </p>
      {toolsQuery.isLoading ? (
        Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className='h-20 w-full' />
        ))
      ) : toolsQuery.data?.length ? (
        toolsQuery.data.map((tool) => (
          <div
            key={tool.name}
            className='flex items-start justify-between gap-4 rounded-md border p-4'
          >
            <div className='flex min-w-0 gap-3'>
              <div className='flex size-9 shrink-0 items-center justify-center rounded-md bg-muted'>
                <Wrench className='size-4 text-muted-foreground' />
              </div>
              <div className='min-w-0 space-y-1'>
                <div className='flex flex-wrap items-center gap-2'>
                  <span className='font-medium'>{tool.name}</span>
                  <Badge variant='outline'>无副作用</Badge>
                </div>
                <p className='text-sm text-muted-foreground'>
                  {tool.description}
                </p>
              </div>
            </div>
            <Switch
              aria-label={`${tool.is_enabled ? '停用' : '启用'} ${tool.name}`}
              checked={tool.is_enabled}
              disabled={updateMutation.isPending}
              onCheckedChange={() => updateMutation.mutate(tool)}
            />
          </div>
        ))
      ) : (
        <div className='flex min-h-32 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground'>
          暂无可用的内置工具
        </div>
      )}
    </div>
  )
}
