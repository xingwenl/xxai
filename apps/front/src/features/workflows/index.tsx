import { useState } from 'react'
import z from 'zod'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { Plus, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { listAgents } from '@/api/agent'
import { listPlatforms } from '@/api/platform'
import {
  createWorkflow,
  deleteWorkflow,
  listWorkflowRuns,
  listWorkflows,
  runWorkflowNow,
  updateWorkflow,
  type Workflow,
  type WorkflowCreate,
} from '@/api/workflow'
import { formatDateTime } from '@/lib/time'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { ConfirmDialog } from '@/components/confirm-dialog'

const PAGE_SIZE = 20

const STATUS_LABEL: Record<
  string,
  { text: string; variant: 'default' | 'secondary' }
> = {
  active: { text: '启用', variant: 'default' },
  paused: { text: '暂停', variant: 'secondary' },
}

/**
 * 新建对话框只收集工作流级配置与第一个步骤，
 * 完整步骤列表一律去详情页的表单式编辑器里维护（v1 无画布）。
 */
const createSchema = z.object({
  name: z.string().min(1, '请输入工作流名称').max(200),
  description: z.string().optional(),
  agent_id: z.number().min(1, '请选择默认智能体'),
  first_prompt: z.string().min(1, '请输入第一个步骤的指令'),
  timeout_seconds: z.number().min(30).max(7200),
  auto_approve: z.boolean(),
  strict_approval: z.boolean(),
})

type CreateForm = z.infer<typeof createSchema>

export function WorkflowsPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [platformId, setPlatformId] = useState<number>()
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [page, setPage] = useState(1)
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<Workflow | null>(null)

  const platformsQuery = useQuery({
    queryKey: ['platforms'],
    queryFn: listPlatforms,
  })
  const activePlatformId = platformId ?? platformsQuery.data?.[0]?.id

  const workflowsQuery = useQuery({
    queryKey: ['workflows', activePlatformId, statusFilter, page],
    queryFn: () =>
      listWorkflows(activePlatformId!, {
        page,
        pageSize: PAGE_SIZE,
        status: statusFilter === 'all' ? undefined : statusFilter,
      }),
    enabled: activePlatformId != null,
  })

  const agentsQuery = useQuery({
    queryKey: ['agents', activePlatformId],
    queryFn: () => listAgents(activePlatformId!, { pageSize: 100 }),
    enabled: activePlatformId != null,
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({
      queryKey: ['workflows', activePlatformId],
    })
    await queryClient.invalidateQueries({
      queryKey: ['workflow-latest-run', activePlatformId],
    })
  }

  const createMutation = useMutation({
    mutationFn: (values: CreateForm) => {
      if (!activePlatformId) throw new Error('请选择平台')
      const input: WorkflowCreate = {
        name: values.name,
        description: values.description?.trim() || null,
        agent_id: values.agent_id,
        steps: [
          {
            step_id: 'step_1',
            name: '步骤 1',
            kind: 'agent',
            prompt: values.first_prompt,
            on_error: 'abort',
          },
        ],
        timeout_seconds: values.timeout_seconds,
        auto_approve: values.auto_approve,
        strict_approval: values.strict_approval,
      }
      return createWorkflow(activePlatformId, input)
    },
    onSuccess: async (workflow) => {
      toast.success('工作流已创建，接下来可以继续补充步骤')
      setCreating(false)
      await invalidate()
      navigate({
        to: '/workflows/$workflowId',
        params: { workflowId: String(workflow.id) },
        search: { platform: activePlatformId },
      })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (workflow: Workflow) =>
      deleteWorkflow(activePlatformId!, workflow.id),
    onSuccess: async (data) => {
      toast.success(`工作流已删除（${data?.deleted ?? 1} 条）`)
      setDeleting(null)
      await invalidate()
    },
  })

  const toggleMutation = useMutation({
    mutationFn: (workflow: Workflow) =>
      updateWorkflow(activePlatformId!, workflow.id, {
        status: workflow.status === 'active' ? 'paused' : 'active',
      }),
    onSuccess: async (workflow) => {
      toast.success(
        workflow.status === 'active' ? '工作流已启用' : '工作流已暂停'
      )
      await invalidate()
    },
  })

  const runMutation = useMutation({
    mutationFn: (workflow: Workflow) =>
      runWorkflowNow(activePlatformId!, workflow.id),
    onSuccess: async (data) => {
      toast.success(data.message)
      await invalidate()
    },
  })

  const workflows = workflowsQuery.data?.items ?? []
  const totalPage = workflowsQuery.data?.totalPage ?? 1

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <div>
          <h1 className='text-2xl font-bold tracking-tight'>工作流</h1>
          <p className='text-sm text-muted-foreground'>
            用有序步骤编排固定流程：每步跑一轮 Agent 或直接调一个工具，
            手动或定时触发，按顺序执行并逐步落库，便于确定性重跑与审计。
          </p>
        </div>
        <Button onClick={() => setCreating(true)} disabled={!activePlatformId}>
          <Plus className='mr-1 size-4' /> 新建工作流
        </Button>
      </div>

      <div className='flex flex-wrap items-center gap-2'>
        <Select
          value={activePlatformId?.toString() ?? ''}
          onValueChange={(value) => {
            setPlatformId(Number(value))
            setPage(1)
          }}
        >
          <SelectTrigger className='w-52'>
            <SelectValue placeholder='选择平台' />
          </SelectTrigger>
          <SelectContent>
            {(platformsQuery.data ?? []).map((platform) => (
              <SelectItem key={platform.id} value={platform.id.toString()}>
                {platform.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={statusFilter}
          onValueChange={(value) => {
            setStatusFilter(value)
            setPage(1)
          }}
        >
          <SelectTrigger className='w-36'>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value='all'>全部状态</SelectItem>
            <SelectItem value='active'>启用</SelectItem>
            <SelectItem value='paused'>暂停</SelectItem>
          </SelectContent>
        </Select>

        <Button
          variant='outline'
          size='icon'
          onClick={() => workflowsQuery.refetch()}
          aria-label='刷新'
        >
          <RefreshCw className='size-4' />
        </Button>
      </div>

      <div className='rounded-md border'>
        <table className='w-full text-sm'>
          <thead className='bg-muted/50 text-left text-muted-foreground'>
            <tr>
              <th className='p-3 font-medium'>名称</th>
              <th className='p-3 font-medium'>状态</th>
              <th className='p-3 font-medium'>版本</th>
              <th className='p-3 font-medium'>步骤数</th>
              <th className='p-3 font-medium'>智能体</th>
              <th className='p-3 font-medium'>最近运行</th>
              <th className='p-3 text-right font-medium'>操作</th>
            </tr>
          </thead>
          <tbody>
            {workflowsQuery.isLoading && (
              <tr>
                <td className='p-3 text-muted-foreground' colSpan={7}>
                  加载中...
                </td>
              </tr>
            )}
            {!workflowsQuery.isLoading && workflows.length === 0 && (
              <tr>
                <td className='p-3 text-muted-foreground' colSpan={7}>
                  暂无工作流
                </td>
              </tr>
            )}
            {workflows.map((workflow) => (
              <tr key={workflow.id} className='border-t'>
                <td className='p-3'>
                  <Link
                    to='/workflows/$workflowId'
                    params={{ workflowId: String(workflow.id) }}
                    search={{ platform: activePlatformId }}
                    className='font-medium hover:underline'
                  >
                    {workflow.name}
                  </Link>
                  {workflow.description && (
                    <p className='mt-1 text-xs text-muted-foreground'>
                      {workflow.description}
                    </p>
                  )}
                </td>
                <td className='p-3'>
                  <Badge
                    variant={
                      STATUS_LABEL[workflow.status]?.variant ?? 'secondary'
                    }
                  >
                    {STATUS_LABEL[workflow.status]?.text ?? workflow.status}
                  </Badge>
                </td>
                <td className='p-3 text-muted-foreground'>
                  v{workflow.version}
                </td>
                <td className='p-3 text-muted-foreground'>
                  {workflow.steps.length}
                  <span className='text-xs'> / {workflow.max_steps}</span>
                </td>
                <td className='p-3 text-muted-foreground'>
                  {agentsQuery.data?.items.find(
                    (agent) => agent.id === workflow.agent_id
                  )?.name ?? `#${workflow.agent_id}`}
                </td>
                <td className='p-3 text-muted-foreground'>
                  <LastRunCell
                    platformId={activePlatformId!}
                    workflowId={workflow.id}
                  />
                </td>
                <td className='p-3 text-right'>
                  <div className='flex justify-end gap-1'>
                    <Button
                      size='sm'
                      variant='outline'
                      onClick={() => runMutation.mutate(workflow)}
                      disabled={runMutation.isPending}
                    >
                      立即运行
                    </Button>
                    <Button
                      size='sm'
                      variant='outline'
                      onClick={() => toggleMutation.mutate(workflow)}
                    >
                      {workflow.status === 'active' ? '暂停' : '启用'}
                    </Button>
                    <Button size='sm' variant='outline' asChild>
                      <Link
                        to='/workflows/$workflowId'
                        params={{ workflowId: String(workflow.id) }}
                        search={{ platform: activePlatformId }}
                      >
                        详情
                      </Link>
                    </Button>
                    <Button
                      size='sm'
                      variant='destructive'
                      onClick={() => setDeleting(workflow)}
                    >
                      删除
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className='flex items-center justify-between'>
        <span className='text-xs text-muted-foreground'>
          共 {workflowsQuery.data?.total ?? 0} 条
        </span>
        <div className='flex gap-2'>
          <Button
            size='sm'
            variant='outline'
            disabled={page <= 1}
            onClick={() => setPage((value) => Math.max(1, value - 1))}
          >
            上一页
          </Button>
          <Button
            size='sm'
            variant='outline'
            disabled={page >= totalPage}
            onClick={() => setPage((value) => value + 1)}
          >
            下一页
          </Button>
        </div>
      </div>

      <CreateWorkflowDialog
        key={creating ? 'open' : 'closed'}
        open={creating}
        onOpenChange={setCreating}
        agents={agentsQuery.data?.items ?? []}
        isSaving={createMutation.isPending}
        onSubmit={(values) => createMutation.mutate(values)}
      />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null)
        }}
        title='删除工作流'
        desc={`确定要删除工作流「${deleting?.name ?? ''}」吗？它的运行记录与步骤明细会一并删除。`}
        confirmText='删除'
        destructive
        isLoading={deleteMutation.isPending}
        handleConfirm={() => deleting && deleteMutation.mutate(deleting)}
      />
    </div>
  )
}

/**
 * 「最近运行时间」：冻结的 Workflow 契约里没有 last_run_at 字段，
 * 只能按行取一次最新运行记录（pageSize=1）来展示，避免为此改动后端契约。
 */
function LastRunCell({
  platformId,
  workflowId,
}: {
  platformId: number
  workflowId: number
}) {
  const runsQuery = useQuery({
    queryKey: ['workflow-latest-run', platformId, workflowId],
    queryFn: () =>
      listWorkflowRuns(platformId, workflowId, { page: 1, pageSize: 1 }),
  })

  if (runsQuery.isLoading) return <span>…</span>
  const latest = runsQuery.data?.items[0]
  if (!latest) return <span>—</span>
  // 运行记录不返回 created_at，展示「有值的最早可读时间」：
  // 已结束看结束时间，在跑看开始时间，排队看计划时间。
  return (
    <span>
      {formatDateTime(
        latest.finished_at ?? latest.started_at ?? latest.planned_at
      )}
    </span>
  )
}

function CreateWorkflowDialog({
  open,
  onOpenChange,
  agents,
  isSaving,
  onSubmit,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  agents: { id: number; name: string }[]
  isSaving: boolean
  onSubmit: (values: CreateForm) => void
}) {
  const form = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    values: {
      name: '',
      description: '',
      agent_id: 0,
      first_prompt: '',
      timeout_seconds: 600,
      auto_approve: true,
      strict_approval: false,
    },
  })

  // 用 useWatch 而不是 form.watch()：后者会被 React Compiler 判定为不可安全记忆化。
  const agentId = useWatch({ control: form.control, name: 'agent_id' })
  const autoApprove = useWatch({ control: form.control, name: 'auto_approve' })
  const strictApproval = useWatch({
    control: form.control,
    name: 'strict_approval',
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-h-[90vh] max-w-2xl overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>新建工作流</DialogTitle>
          <DialogDescription>
            先建好工作流级配置和第一步，保存后进入详情页继续增删、调序与绑定。
          </DialogDescription>
        </DialogHeader>
        <form
          id='workflow-create-form'
          onSubmit={form.handleSubmit(onSubmit)}
          className='grid gap-4'
        >
          <div>
            <Label>名称</Label>
            <Input {...form.register('name')} placeholder='每日巡检' />
            <p className='mt-1 text-xs text-destructive'>
              {form.formState.errors.name?.message}
            </p>
          </div>

          <div>
            <Label>说明</Label>
            <Textarea
              rows={2}
              placeholder='这条工作流的用途，便于后台识别'
              {...form.register('description')}
            />
          </div>

          <div>
            <Label>默认智能体</Label>
            <Select
              value={agentId ? String(agentId) : ''}
              onValueChange={(value) =>
                form.setValue('agent_id', Number(value), {
                  shouldValidate: true,
                })
              }
            >
              <SelectTrigger>
                <SelectValue placeholder='选择默认智能体' />
              </SelectTrigger>
              <SelectContent>
                {agents.map((agent) => (
                  <SelectItem key={agent.id} value={String(agent.id)}>
                    {agent.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className='mt-1 text-xs text-destructive'>
              {form.formState.errors.agent_id?.message}
            </p>
          </div>

          <div>
            <Label>第一个步骤的指令</Label>
            <Textarea
              rows={4}
              placeholder='第一步发给智能体的完整指令，例如：拉取今日异常订单并汇总'
              {...form.register('first_prompt')}
            />
            <p className='mt-1 text-xs text-destructive'>
              {form.formState.errors.first_prompt?.message}
            </p>
            <p className='mt-1 text-xs text-muted-foreground'>
              这一步会作为「步骤 1」的 Agent
              步骤创建，之后可在详情页改成工具步骤或继续添加步骤。
            </p>
          </div>

          <div className='grid gap-3 sm:grid-cols-2'>
            <div className='flex items-center justify-between rounded-md border p-3'>
              <div>
                <Label>自动批准工具</Label>
                <p className='text-xs text-muted-foreground'>
                  无人值守时自动批准需要确认的工具调用
                </p>
              </div>
              <Switch
                checked={autoApprove}
                onCheckedChange={(value) =>
                  form.setValue('auto_approve', value)
                }
              />
            </div>
            <div className='flex items-center justify-between rounded-md border p-3'>
              <div>
                <Label>严格模式</Label>
                <p className='text-xs text-muted-foreground'>
                  只自动批准页面跳转类工具
                </p>
              </div>
              <Switch
                checked={strictApproval}
                onCheckedChange={(value) =>
                  form.setValue('strict_approval', value)
                }
              />
            </div>
            <div>
              <Label>整条超时（秒）</Label>
              <Input
                type='number'
                {...form.register('timeout_seconds', { valueAsNumber: true })}
              />
              <p className='mt-1 text-xs text-destructive'>
                {form.formState.errors.timeout_seconds?.message}
              </p>
            </div>
          </div>

          <p className='text-xs text-muted-foreground'>
            支付类（financial）操作在任何配置下都不会自动批准。
          </p>
        </form>
        <DialogFooter>
          <Button type='submit' form='workflow-create-form' disabled={isSaving}>
            {isSaving ? '创建中...' : '创建并继续编辑'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
