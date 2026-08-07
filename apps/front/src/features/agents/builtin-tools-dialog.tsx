import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Wrench } from 'lucide-react'
import { toast } from 'sonner'
import type { Agent } from '@/api/agent'
import {
  listAgentBuiltinTools,
  updateAgentBuiltinTool,
  type AgentBuiltinTool,
} from '@/api/builtin-tools'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'

type BuiltinToolsDialogProps = {
  platformId: number
  agent: Agent
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function BuiltinToolsDialog({
  platformId,
  agent,
  open,
  onOpenChange,
}: BuiltinToolsDialogProps) {
  const queryClient = useQueryClient()
  const queryKey = ['agent-builtin-tools', platformId, agent.id] as const
  const toolsQuery = useQuery({
    queryKey,
    queryFn: () => listAgentBuiltinTools(platformId, agent.id),
    enabled: open,
  })
  const handleUpdated = (updated: AgentBuiltinTool) => {
    queryClient.setQueryData<AgentBuiltinTool[]>(queryKey, (current = []) =>
      current.map((tool) => (tool.name === updated.name ? updated : tool))
    )
    toast.success(updated.is_enabled ? '工具已启用' : '工具已停用')
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-h-[85vh] max-w-2xl overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>{agent.name} · 内置工具</DialogTitle>
          <DialogDescription>
            启用后，智能体可在下一轮对话中调用对应工具。
          </DialogDescription>
        </DialogHeader>

        <div className='space-y-3 py-1'>
          {toolsQuery.isLoading ? (
            Array.from({ length: 2 }).map((_, index) => (
              <Skeleton key={index} className='h-24 w-full' />
            ))
          ) : toolsQuery.isError ? (
            <div className='flex min-h-32 flex-col items-center justify-center gap-3 rounded-md border border-dashed p-6 text-center'>
              <p className='text-sm text-muted-foreground'>内置工具加载失败</p>
              <Button
                size='sm'
                variant='outline'
                onClick={() => toolsQuery.refetch()}
                disabled={toolsQuery.isFetching}
              >
                <RefreshCw
                  className={`me-2 size-4 ${toolsQuery.isFetching ? 'animate-spin' : ''}`}
                />
                重试
              </Button>
            </div>
          ) : toolsQuery.data?.length ? (
            toolsQuery.data.map((tool) => (
              <BuiltinToolRow
                key={tool.name}
                platformId={platformId}
                agentId={agent.id}
                tool={tool}
                onUpdated={handleUpdated}
              />
            ))
          ) : (
            <div className='flex min-h-32 items-center justify-center rounded-md border border-dashed p-6 text-sm text-muted-foreground'>
              暂无可用的内置工具
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant='outline' onClick={() => onOpenChange(false)}>
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function BuiltinToolRow({
  platformId,
  agentId,
  tool,
  onUpdated,
}: {
  platformId: number
  agentId: number
  tool: AgentBuiltinTool
  onUpdated: (tool: AgentBuiltinTool) => void
}) {
  const updateMutation = useMutation({
    mutationFn: (isEnabled: boolean) =>
      updateAgentBuiltinTool(platformId, agentId, tool.name, isEnabled),
    onSuccess: onUpdated,
    onError: () => toast.error('工具状态更新失败'),
  })

  return (
    <div className='flex items-start justify-between gap-4 rounded-md border p-4'>
      <div className='flex min-w-0 gap-3'>
        <div className='flex size-9 shrink-0 items-center justify-center rounded-md bg-muted'>
          <Wrench className='size-4 text-muted-foreground' />
        </div>
        <div className='min-w-0 space-y-1'>
          <div className='flex flex-wrap items-center gap-2'>
            <span className='font-medium'>{tool.name}</span>
            <Badge variant='outline'>无副作用</Badge>
          </div>
          <p className='text-sm text-muted-foreground'>{tool.description}</p>
        </div>
      </div>
      <Switch
        aria-label={`${tool.is_enabled ? '停用' : '启用'} ${tool.name}`}
        checked={tool.is_enabled}
        disabled={updateMutation.isPending}
        onCheckedChange={(isEnabled) => updateMutation.mutate(isEnabled)}
      />
    </div>
  )
}
