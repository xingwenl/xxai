import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link2 } from 'lucide-react'
import { toast } from 'sonner'
import {
  bindAgentHostTool,
  listAgentHostTools,
  listHostTools,
  unbindAgentHostTool,
} from '@/api/host-tools'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'

export function HostToolsSection({
  platformId,
  agentId,
}: {
  platformId?: number
  agentId: number
}) {
  const queryClient = useQueryClient()
  const policiesQuery = useQuery({
    queryKey: ['host-tools', platformId],
    queryFn: () => listHostTools(platformId!),
    enabled: platformId != null,
  })
  const bindingsQuery = useQuery({
    queryKey: ['agent-host-tools', platformId, agentId],
    queryFn: () => listAgentHostTools(platformId!, agentId),
    enabled: platformId != null,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ['agent-host-tools', platformId, agentId],
      }),
      queryClient.invalidateQueries({
        queryKey: ['agent', platformId, agentId],
      }),
    ])
  }
  const bindMutation = useMutation({
    mutationFn: (toolId: number) =>
      bindAgentHostTool(platformId!, agentId, toolId),
    onSuccess: async () => {
      toast.success('宿主工具已关联')
      await invalidate()
    },
    onError: () => toast.error('关联失败，请重试'),
  })
  const unbindMutation = useMutation({
    mutationFn: (toolId: number) =>
      unbindAgentHostTool(platformId!, agentId, toolId),
    onSuccess: async () => {
      toast.success('宿主工具已解除关联')
      await invalidate()
    },
    onError: () => toast.error('解除关联失败，请重试'),
  })
  const rows = (policiesQuery.data ?? []).map((policy) => ({
    policy,
    binding: bindingsQuery.data?.find((item) => item.tool_id === policy.id),
  }))
  const busy = bindMutation.isPending || unbindMutation.isPending

  return (
    <div className='space-y-3'>
      <p className='text-sm text-muted-foreground'>
        按工具关联；全局停用的工具不可启用。
      </p>
      {policiesQuery.isLoading || bindingsQuery.isLoading ? (
        Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className='h-20 w-full' />
        ))
      ) : rows.length ? (
        rows.map(({ policy, binding }) => (
          <div
            key={policy.id}
            className='flex items-start justify-between gap-4 rounded-md border p-4'
          >
            <div className='flex min-w-0 gap-3'>
              <div className='flex size-9 shrink-0 items-center justify-center rounded-md bg-muted'>
                <Link2 className='size-4 text-muted-foreground' />
              </div>
              <div className='min-w-0 space-y-1'>
                <div className='flex flex-wrap items-center gap-2'>
                  <span className='font-medium'>{policy.name}</span>
                  <Badge variant='outline'>{policy.side_effect}</Badge>
                  {!policy.is_enabled && (
                    <Badge variant='secondary'>全局已停用</Badge>
                  )}
                </div>
                <p className='text-sm text-muted-foreground'>
                  {policy.description}
                </p>
              </div>
            </div>
            <Switch
              aria-label={`${binding?.is_enabled ? '解除' : '关联'} ${policy.name}`}
              checked={binding?.is_enabled ?? false}
              disabled={!policy.is_enabled || busy}
              onCheckedChange={(checked) =>
                checked
                  ? bindMutation.mutate(policy.id)
                  : unbindMutation.mutate(policy.id)
              }
            />
          </div>
        ))
      ) : (
        <div className='flex min-h-32 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground'>
          暂无宿主工具策略
        </div>
      )}
    </div>
  )
}
