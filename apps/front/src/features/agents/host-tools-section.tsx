import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Layers, Link2 } from 'lucide-react'
import { toast } from 'sonner'
import { listToolGroups, type ToolGroup } from '@/api/builtin-tools'
import {
  bindAgentHostTool,
  listAgentHostTools,
  listHostTools,
  unbindAgentHostTool,
  type HostToolPolicy,
} from '@/api/host-tools'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'

type Row = { policy: HostToolPolicy; bound: boolean }

type GroupSection = {
  group: string
  title: string
  description: string
  eager: boolean
  rows: Row[]
}

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
  // 分组只用于展示：组的来源是宿主工具策略名与运行期声明，页面不写组关系。
  const groupsQuery = useQuery({
    queryKey: ['tool-groups', platformId],
    queryFn: () => listToolGroups(platformId!),
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
  const rows: Row[] = (policiesQuery.data ?? []).map((policy) => ({
    policy,
    bound:
      bindingsQuery.data?.find((item) => item.tool_id === policy.id)
        ?.is_enabled ?? false,
  }))
  const sections = buildSections(rows, groupsQuery.data?.host)
  const busy = bindMutation.isPending || unbindMutation.isPending

  return (
    <div className='space-y-3'>
      <p className='text-sm text-muted-foreground'>
        按工具组展示；「常驻」组每轮都可用，「按需加载」组由智能体在需要时自行加载。
        全局停用的工具不可启用。
      </p>
      {policiesQuery.isLoading ||
      bindingsQuery.isLoading ||
      groupsQuery.isLoading ? (
        Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className='h-20 w-full' />
        ))
      ) : sections.length ? (
        sections.map((section) => (
          <HostToolGroupCard
            key={section.group}
            section={section}
            busy={busy}
            onToggle={(row, checked) =>
              checked
                ? bindMutation.mutate(row.policy.id)
                : unbindMutation.mutate(row.policy.id)
            }
          />
        ))
      ) : (
        <div className='flex min-h-32 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground'>
          暂无宿主工具策略
        </div>
      )}
    </div>
  )
}

/** 按后端返回的组目录切分策略列表；目录没覆盖到的策略落到末尾，避免悄悄消失。 */
function buildSections(
  rows: Row[],
  groups: ToolGroup[] | undefined
): GroupSection[] {
  const groupOf = new Map<string, string>()
  for (const group of groups ?? []) {
    for (const name of group.tool_names) groupOf.set(name, group.group)
  }

  const byGroup = new Map<string, Row[]>()
  const rest: Row[] = []
  for (const row of rows) {
    const group = groupOf.get(row.policy.name)
    if (!group) {
      rest.push(row)
      continue
    }
    const bucket = byGroup.get(group)
    if (bucket) bucket.push(row)
    else byGroup.set(group, [row])
  }

  const sections: GroupSection[] = (groups ?? [])
    .map((group) => ({
      group: group.group,
      title: group.title,
      description: group.description,
      eager: group.eager,
      rows: byGroup.get(group.group) ?? [],
    }))
    .filter((section) => section.rows.length > 0)
  if (rest.length > 0) {
    sections.push({
      group: 'ungrouped',
      title: '未分组',
      description: '目录未覆盖的宿主工具，仍可正常关联',
      eager: false,
      rows: rest,
    })
  }
  return sections
}

function HostToolGroupCard({
  section,
  busy,
  onToggle,
}: {
  section: GroupSection
  busy: boolean
  onToggle: (row: Row, checked: boolean) => void
}) {
  return (
    <Collapsible defaultOpen>
      <div className='flex items-center justify-between gap-4 rounded-md border p-4'>
        <div className='flex min-w-0 items-center gap-3'>
          <div className='flex size-9 shrink-0 items-center justify-center rounded-md bg-muted'>
            <Layers className='size-4 text-muted-foreground' />
          </div>
          <div className='min-w-0 space-y-1'>
            <div className='flex flex-wrap items-center gap-2'>
              <span className='font-medium'>{section.title}</span>
              <Badge variant={section.eager ? 'default' : 'outline'}>
                {section.eager ? '常驻' : '按需加载'}
              </Badge>
              <span className='text-xs text-muted-foreground'>
                {section.rows.length} 个工具
              </span>
            </div>
            <p className='truncate text-xs text-muted-foreground'>
              {section.description}
            </p>
          </div>
        </div>
        <CollapsibleTrigger asChild>
          <Button
            size='sm'
            variant='ghost'
            aria-label={`展开 ${section.title}`}
          >
            <ChevronDown className='size-4' />
          </Button>
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent>
        <div className='space-y-2 rounded-b-md border-x border-b p-3'>
          {section.rows.map((row) => (
            <div
              key={row.policy.id}
              className='flex items-start justify-between gap-4 rounded-md border p-3'
            >
              <div className='flex min-w-0 gap-3'>
                <div className='flex size-9 shrink-0 items-center justify-center rounded-md bg-muted'>
                  <Link2 className='size-4 text-muted-foreground' />
                </div>
                <div className='min-w-0 space-y-1'>
                  <div className='flex flex-wrap items-center gap-2'>
                    <span className='font-medium'>{row.policy.name}</span>
                    <Badge variant='outline'>{row.policy.side_effect}</Badge>
                    {!row.policy.is_enabled && (
                      <Badge variant='secondary'>全局已停用</Badge>
                    )}
                  </div>
                  <p className='text-sm text-muted-foreground'>
                    {row.policy.description}
                  </p>
                </div>
              </div>
              <Switch
                aria-label={`${row.bound ? '解除' : '关联'} ${row.policy.name}`}
                checked={row.bound}
                disabled={!row.policy.is_enabled || busy}
                onCheckedChange={(checked) => onToggle(row, checked)}
              />
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
