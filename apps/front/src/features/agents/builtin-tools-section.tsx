import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Layers, Wrench } from 'lucide-react'
import { toast } from 'sonner'
import {
  listAgentBuiltinTools,
  listToolGroups,
  updateAgentBuiltinTool,
  type AgentBuiltinTool,
  type ToolGroup,
} from '@/api/builtin-tools'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'

type GroupSection = {
  group: string
  title: string
  description: string
  eager: boolean
  tools: AgentBuiltinTool[]
}

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
  // 分组只用于展示：组与成员关系由后端常量与工具声明决定，这里没有写入口。
  const groupsQuery = useQuery({
    queryKey: ['tool-groups', platformId],
    queryFn: () => listToolGroups(platformId!),
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

  const sections = buildSections(
    toolsQuery.data ?? [],
    groupsQuery.data?.builtin
  )

  return (
    <div className='space-y-3'>
      <p className='text-sm text-muted-foreground'>
        工具按业务域分组；「常驻」组每轮都可用，「按需加载」组由智能体在需要时自行加载。
        启用后，智能体可在下一轮对话中调用对应工具。
      </p>
      {toolsQuery.isLoading || groupsQuery.isLoading ? (
        Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className='h-20 w-full' />
        ))
      ) : sections.length ? (
        sections.map((section) => (
          <ToolGroupCard
            key={section.group}
            section={section}
            disabled={updateMutation.isPending}
            onToggle={(tool) => updateMutation.mutate(tool)}
          />
        ))
      ) : (
        <div className='flex min-h-32 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground'>
          暂无可用的内置工具
        </div>
      )}
    </div>
  )
}

/** 把扁平工具列表按分组目录切成若干段；接口没覆盖到的工具落到末尾，避免悄悄消失。 */
function buildSections(
  tools: AgentBuiltinTool[],
  groups: ToolGroup[] | undefined
): GroupSection[] {
  const groupOf = new Map<string, string>()
  for (const group of groups ?? []) {
    for (const name of group.tool_names) groupOf.set(name, group.group)
  }

  const byGroup = new Map<string, AgentBuiltinTool[]>()
  const ungrouped: AgentBuiltinTool[] = []
  for (const tool of tools) {
    const group = groupOf.get(tool.name)
    if (!group) {
      ungrouped.push(tool)
      continue
    }
    const bucket = byGroup.get(group)
    if (bucket) bucket.push(tool)
    else byGroup.set(group, [tool])
  }

  const sections: GroupSection[] = (groups ?? [])
    .map((group) => ({
      group: group.group,
      title: group.title,
      description: group.description,
      eager: group.eager,
      tools: byGroup.get(group.group) ?? [],
    }))
    .filter((section) => section.tools.length > 0)
  if (ungrouped.length > 0) {
    sections.push({
      group: 'ungrouped',
      title: '未分组',
      description: '接口未返回分组的工具，仍可正常启用',
      eager: false,
      tools: ungrouped,
    })
  }
  return sections
}

function ToolGroupCard({
  section,
  disabled,
  onToggle,
}: {
  section: GroupSection
  disabled: boolean
  onToggle: (tool: AgentBuiltinTool) => void
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
                {section.tools.length} 个工具
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
          {section.tools.map((tool) => (
            <div
              key={tool.name}
              className='flex items-start justify-between gap-4 rounded-md border p-3'
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
                disabled={disabled}
                onCheckedChange={() => onToggle(tool)}
              />
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
