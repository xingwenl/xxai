import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Cable, ChevronDown } from 'lucide-react'
import { toast } from 'sonner'
import {
  bindMcpServer,
  listMcpBindings,
  listMcpServerTools,
  listMcpServers,
  unbindMcpServer,
} from '@/api/mcp-servers'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

export function McpToolsSection({
  platformId,
  agentId,
}: {
  platformId?: number
  agentId: number
}) {
  const queryClient = useQueryClient()
  const serversQuery = useQuery({
    queryKey: ['mcp-servers', platformId],
    queryFn: () => listMcpServers(platformId!, { pageSize: 100 }),
    enabled: platformId != null,
  })
  const bindingsQuery = useQuery({
    queryKey: ['agent-mcp-bindings', platformId, agentId],
    queryFn: () => listMcpBindings(platformId!, agentId),
    enabled: platformId != null,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ['agent-mcp-bindings', platformId, agentId],
      }),
      queryClient.invalidateQueries({
        queryKey: ['agent', platformId, agentId],
      }),
    ])
  }
  const bindMutation = useMutation({
    mutationFn: (serverId: number) =>
      bindMcpServer(platformId!, agentId, serverId),
    onSuccess: async () => {
      toast.success('MCP 服务已关联')
      await invalidate()
    },
    onError: () => toast.error('关联失败，请重试'),
  })
  const unbindMutation = useMutation({
    mutationFn: (serverId: number) =>
      unbindMcpServer(platformId!, agentId, serverId),
    onSuccess: async () => {
      toast.success('MCP 服务已解除关联')
      await invalidate()
    },
    onError: () => toast.error('解除关联失败，请重试'),
  })
  const rows = (serversQuery.data?.items ?? []).map((server) => ({
    server,
    binding: bindingsQuery.data?.find((item) => item.server_id === server.id),
  }))
  const busy = bindMutation.isPending || unbindMutation.isPending

  return (
    <div className='space-y-3'>
      <p className='text-sm text-muted-foreground'>
        按 MCP 服务关联；工具可用性与副作用策略在 MCP 管理页维护。
      </p>
      {serversQuery.isLoading || bindingsQuery.isLoading ? (
        Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className='h-20 w-full' />
        ))
      ) : rows.length ? (
        rows.map(({ server, binding }) => (
          <McpServerRow
            key={server.id}
            platformId={platformId!}
            server={server}
            bound={!!binding}
            busy={busy}
            onToggle={(checked) =>
              checked
                ? bindMutation.mutate(server.id)
                : unbindMutation.mutate(server.id)
            }
          />
        ))
      ) : (
        <div className='flex min-h-32 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground'>
          暂无 MCP 服务，请先到 MCP 管理创建。
        </div>
      )}
    </div>
  )
}

function McpServerRow({
  platformId,
  server,
  bound,
  busy,
  onToggle,
}: {
  platformId: number
  server: { id: number; name: string; slug: string; is_active: boolean }
  bound: boolean
  busy: boolean
  onToggle: (checked: boolean) => void
}) {
  return (
    <Collapsible>
      <div className='flex items-center justify-between gap-4 rounded-md border p-4'>
        <div className='flex min-w-0 items-center gap-3'>
          <div className='flex size-9 shrink-0 items-center justify-center rounded-md bg-muted'>
            <Cable className='size-4 text-muted-foreground' />
          </div>
          <div className='min-w-0'>
            <div className='flex flex-wrap items-center gap-2'>
              <span className='font-medium'>{server.name}</span>
              <Badge variant={server.is_active ? 'outline' : 'secondary'}>
                {server.is_active ? '启用' : '停用'}
              </Badge>
            </div>
            <div className='truncate text-xs text-muted-foreground'>
              {server.slug}
            </div>
          </div>
        </div>
        <div className='flex shrink-0 items-center gap-2'>
          <CollapsibleTrigger asChild>
            <Button size='sm' variant='ghost'>
              <ChevronDown className='size-4' />
              工具
            </Button>
          </CollapsibleTrigger>
          <Switch
            aria-label={`${bound ? '解除' : '关联'} ${server.name}`}
            checked={bound}
            disabled={busy}
            onCheckedChange={onToggle}
          />
        </div>
      </div>
      <CollapsibleContent>
        <div className='rounded-b-md border-x border-b p-3'>
          <McpServerToolsList platformId={platformId} serverId={server.id} />
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

function McpServerToolsList({
  platformId,
  serverId,
}: {
  platformId: number
  serverId: number
}) {
  const toolsQuery = useQuery({
    queryKey: ['mcp-server-tools', platformId, serverId],
    queryFn: () => listMcpServerTools(platformId, serverId),
    enabled: platformId != null,
  })
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>工具</TableHead>
          <TableHead>描述</TableHead>
          <TableHead>允许调用</TableHead>
          <TableHead>副作用</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {toolsQuery.isLoading ? (
          <TableRow>
            <TableCell colSpan={4}>
              <Skeleton className='h-8 w-full' />
            </TableCell>
          </TableRow>
        ) : toolsQuery.data?.length ? (
          toolsQuery.data.map((tool) => (
            <TableRow key={tool.id}>
              <TableCell className='font-mono text-xs font-medium'>
                {tool.name}
              </TableCell>
              <TableCell className='max-w-md truncate text-sm text-muted-foreground'>
                {tool.description || '-'}
              </TableCell>
              <TableCell>
                <Badge variant={tool.is_allowed ? 'default' : 'secondary'}>
                  {tool.is_allowed ? '允许' : '禁用'}
                </Badge>
              </TableCell>
              <TableCell className='text-xs'>{tool.side_effect}</TableCell>
            </TableRow>
          ))
        ) : (
          <TableRow>
            <TableCell
              colSpan={4}
              className='h-16 text-center text-sm text-muted-foreground'
            >
              该服务暂无可发现工具
            </TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  )
}
