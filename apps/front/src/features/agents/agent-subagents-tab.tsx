import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, Info, Plus, Users, X } from 'lucide-react'
import { toast } from 'sonner'
import {
  listAgentSubagents,
  replaceAgentSubagents,
  type AgentSubagent,
  type AgentSubagentCandidate,
  type AgentSubagentListData,
  type AgentSubagentUpdateItem,
} from '@/api/agent'
import { handleServerError } from '@/lib/handle-server-error'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'

/** 服务端响应的空态兜底：fallback 默认 true，与「未配置即全平台兜底」的业务语义一致。 */
const EMPTY_DATA: AgentSubagentListData = {
  items: [],
  fallback: true,
  available: [],
}

export function AgentSubagentsTab({
  platformId,
  agentId,
}: {
  platformId?: number
  agentId: number
}) {
  const queryClient = useQueryClient()
  const queryKey = ['agent-subagents', platformId, agentId]
  const subagentsQuery = useQuery({
    queryKey,
    queryFn: () => listAgentSubagents(platformId!, agentId),
    enabled: platformId != null,
  })
  // 整表替换：顺序即运行期提示顺序，因此改启用状态、排序、添加、移除都提交完整数组
  const saveMutation = useMutation({
    mutationFn: (items: AgentSubagentUpdateItem[]) =>
      replaceAgentSubagents(platformId!, agentId, items),
    onSuccess: (next) => {
      // PUT 返回与 GET 同构的响应体，直接回填可让 items / available 同步收敛
      queryClient.setQueryData(queryKey, next)
      toast.success('子智能体配置已保存')
    },
    onError: (error) => handleServerError(error),
  })

  const data = subagentsQuery.data ?? EMPTY_DATA
  const rows = [...data.items].sort((a, b) => a.sort_order - b.sort_order)
  const available = data.available
  const busy = saveMutation.isPending

  const saveRows = (next: AgentSubagent[]) => {
    if (platformId == null) {
      toast.error('请选择平台')
      return
    }
    saveMutation.mutate(
      next.map((row) => ({
        child_agent_id: row.child_agent_id,
        enabled: row.enabled,
      }))
    )
  }

  const toggleEnabled = (target: AgentSubagent) =>
    saveRows(
      rows.map((row) =>
        row.child_agent_id === target.child_agent_id
          ? { ...row, enabled: !row.enabled }
          : row
      )
    )

  const move = (index: number, offset: -1 | 1) => {
    const target = index + offset
    if (target < 0 || target >= rows.length) return
    const next = [...rows]
    const [moved] = next.splice(index, 1)
    next.splice(target, 0, moved)
    saveRows(next)
  }

  const remove = (target: AgentSubagent) =>
    saveRows(rows.filter((row) => row.child_agent_id !== target.child_agent_id))

  const add = (candidate: AgentSubagentCandidate) =>
    saveRows([
      ...rows,
      {
        child_agent_id: candidate.id,
        slug: candidate.slug,
        name: candidate.name,
        description: candidate.description ?? null,
        enabled: true,
        sort_order: rows.length,
        // 候选只来自已发布且启用的智能体，本地乐观值按候选口径初始化；
        // 保存成功后由 PUT 响应回填真实状态。
        published: true,
        active: true,
      },
    ])

  const addButton = (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size='sm' disabled={busy || available.length === 0}>
          <Plus className='size-4' />
          添加子智能体
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align='end' className='w-64'>
        <DropdownMenuLabel>可添加的智能体</DropdownMenuLabel>
        {available.map((candidate) => (
          <DropdownMenuItem
            key={candidate.id}
            onSelect={() => add(candidate)}
            className='flex-col items-start gap-0.5'
          >
            <div className='flex w-full items-center gap-2'>
              <span className='truncate font-medium'>{candidate.name}</span>
              <Badge variant='outline' className='shrink-0'>
                {candidate.slug}
              </Badge>
            </div>
            {candidate.description && (
              <span className='line-clamp-2 text-xs text-muted-foreground'>
                {candidate.description}
              </span>
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )

  return (
    <div className='space-y-3'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <div className='flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground'>
          <span>已绑定 {rows.length} 个子智能体</span>
          <span>·</span>
          <span>顺序即委派提示顺序，变更在下一轮对话生效</span>
        </div>
        {/* 空列表的添加入口放在下方空态里，避免同一入口出现两次 */}
        {rows.length > 0 && addButton}
      </div>

      {data.fallback && (
        <div className='flex items-start gap-2 rounded-md border border-dashed bg-muted/40 p-3 text-sm text-muted-foreground'>
          <Info className='mt-0.5 size-4 shrink-0' />
          <p>未配置子智能体时，委派可派本平台全部已发布智能体（排除自己）</p>
        </div>
      )}

      {subagentsQuery.isLoading ? (
        Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className='h-20 w-full' />
        ))
      ) : subagentsQuery.isError ? (
        <div className='flex min-h-32 flex-col items-center justify-center gap-3 rounded-md border border-dashed p-6 text-center'>
          <p className='text-sm text-muted-foreground'>子智能体加载失败</p>
          <Button
            size='sm'
            variant='outline'
            onClick={() => subagentsQuery.refetch()}
            disabled={subagentsQuery.isFetching}
          >
            重试
          </Button>
        </div>
      ) : rows.length ? (
        <div className='space-y-3'>
          {rows.map((row, index) => (
            <div
              key={row.child_agent_id}
              className='flex items-start justify-between gap-4 rounded-md border p-4'
            >
              <div className='flex min-w-0 gap-3'>
                <div className='flex size-9 shrink-0 items-center justify-center rounded-md bg-muted'>
                  <Users className='size-4 text-muted-foreground' />
                </div>
                <div className='min-w-0 space-y-1'>
                  <div className='flex flex-wrap items-center gap-2'>
                    <span className='font-medium'>{row.name}</span>
                    <Badge variant='outline'>{row.slug}</Badge>
                    {!row.enabled && <Badge variant='secondary'>已停用</Badge>}
                    {!row.published && (
                      <Badge variant='destructive'>未发布</Badge>
                    )}
                    {!row.active && (
                      <Badge variant='secondary'>Agent 已停用</Badge>
                    )}
                  </div>
                  <p className='text-sm text-muted-foreground'>
                    {row.description || '暂无描述'}
                  </p>
                </div>
              </div>
              <div className='flex shrink-0 items-center gap-1'>
                <Switch
                  aria-label={`${row.enabled ? '停用' : '启用'} ${row.name}`}
                  checked={row.enabled}
                  disabled={busy}
                  onCheckedChange={() => toggleEnabled(row)}
                />
                <Button
                  variant='ghost'
                  size='icon'
                  className='size-8'
                  aria-label={`上移 ${row.name}`}
                  disabled={busy || index === 0}
                  onClick={() => move(index, -1)}
                >
                  <ArrowUp className='size-4' />
                </Button>
                <Button
                  variant='ghost'
                  size='icon'
                  className='size-8'
                  aria-label={`下移 ${row.name}`}
                  disabled={busy || index === rows.length - 1}
                  onClick={() => move(index, 1)}
                >
                  <ArrowDown className='size-4' />
                </Button>
                <Button
                  variant='ghost'
                  size='icon'
                  className='size-8 text-muted-foreground hover:text-destructive'
                  aria-label={`移除 ${row.name}`}
                  disabled={busy}
                  onClick={() => remove(row)}
                >
                  <X className='size-4' />
                </Button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className='flex min-h-32 flex-col items-center justify-center gap-3 rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground'>
          {available.length ? (
            <>
              <p>还没有绑定子智能体，可从本平台已发布智能体中添加。</p>
              {addButton}
            </>
          ) : (
            <p>暂无可添加的子智能体，请先在本平台发布其他智能体。</p>
          )}
        </div>
      )}
    </div>
  )
}
