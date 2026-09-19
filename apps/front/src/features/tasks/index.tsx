import { useState } from 'react'
import z from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Plus, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { listAgents } from '@/api/agent'
import { listPlatforms } from '@/api/platform'
import {
  createTask,
  deleteTask,
  listTasks,
  runTaskNow,
  updateTask,
  type Task,
  type TaskInput,
} from '@/api/task'
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

/**
 * 触发规则预设：前端只负责把预设翻译成五段式 cron，
 * 「下一次运行时间」一律由后端计算返回，前端不引入 cron 解析库。
 */
const TRIGGER_PRESETS = [
  { value: 'interval', label: '按间隔', cron: '*/30 * * * *' },
  { value: 'daily', label: '每天', cron: '0 9 * * *' },
  { value: 'weekly', label: '每周', cron: '0 9 * * 1' },
  { value: 'workday', label: '工作日', cron: '0 9 * * 1-5' },
  { value: 'custom', label: '自定义 cron', cron: '' },
] as const

const TIMEZONES = [
  'Asia/Shanghai',
  'UTC',
  'Asia/Tokyo',
  'Asia/Singapore',
  'America/New_York',
  'Europe/London',
]

const taskSchema = z
  .object({
    name: z.string().min(1, '请输入任务名称').max(200),
    prompt: z.string().min(1, '请输入到点执行的指令'),
    agent_id: z.number({ message: '请选择智能体' }),
    trigger_type: z.enum(['cron', 'once']),
    cron_expression: z.string().optional(),
    run_at: z.string().optional(),
    timezone: z.string().min(1),
    auto_approve: z.boolean(),
    strict_approval: z.boolean(),
    timeout_seconds: z.number().min(30).max(7200),
  })
  .refine(
    (value) =>
      value.trigger_type !== 'cron' ||
      (value.cron_expression ?? '').trim().length > 0,
    { message: '请输入 cron 表达式', path: ['cron_expression'] }
  )
  .refine(
    (value) =>
      value.trigger_type !== 'once' || (value.run_at ?? '').trim().length > 0,
    { message: '请选择执行时间', path: ['run_at'] }
  )

type TaskForm = z.infer<typeof taskSchema>

const STATUS_LABEL: Record<
  string,
  { text: string; variant: 'default' | 'secondary' }
> = {
  active: { text: '启用', variant: 'default' },
  paused: { text: '暂停', variant: 'secondary' },
}

const RUN_STATUS_LABEL: Record<string, string> = {
  running: '执行中',
  completed: '已完成',
  failed: '失败',
  skipped: '已跳过',
}

export function TasksPage() {
  const queryClient = useQueryClient()
  const [platformId, setPlatformId] = useState<number>()
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [editing, setEditing] = useState<Task | null | undefined>()
  const [deleting, setDeleting] = useState<Task | null>(null)

  const platformsQuery = useQuery({
    queryKey: ['platforms'],
    queryFn: listPlatforms,
  })
  const activePlatformId = platformId ?? platformsQuery.data?.[0]?.id

  const tasksQuery = useQuery({
    queryKey: ['tasks', activePlatformId, statusFilter],
    queryFn: () =>
      listTasks(activePlatformId!, {
        status: statusFilter === 'all' ? undefined : statusFilter,
      }),
    enabled: activePlatformId != null,
  })

  const agentsQuery = useQuery({
    queryKey: ['agents', activePlatformId],
    queryFn: () => listAgents(activePlatformId!, { pageSize: 100 }),
    enabled: activePlatformId != null,
  })

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['tasks', activePlatformId] })

  const saveMutation = useMutation({
    mutationFn: (values: TaskForm) => {
      if (!activePlatformId) throw new Error('请选择平台')
      const input = toTaskInput(values)
      return editing
        ? updateTask(activePlatformId, editing.id, input)
        : createTask(activePlatformId, input)
    },
    onSuccess: async () => {
      toast.success(editing ? '任务已更新' : '任务已创建')
      setEditing(undefined)
      await invalidate()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (task: Task) => deleteTask(activePlatformId!, task.id),
    onSuccess: async () => {
      toast.success('任务已删除')
      setDeleting(null)
      await invalidate()
    },
  })

  const toggleMutation = useMutation({
    mutationFn: (task: Task) =>
      updateTask(activePlatformId!, task.id, {
        status: task.status === 'active' ? 'paused' : 'active',
      }),
    onSuccess: async (task) => {
      toast.success(task.status === 'active' ? '任务已启用' : '任务已暂停')
      await invalidate()
    },
  })

  const runMutation = useMutation({
    mutationFn: (task: Task) => runTaskNow(activePlatformId!, task.id),
    onSuccess: async (data) => {
      toast.success(data.message)
      await invalidate()
    },
  })

  const tasks = tasksQuery.data?.items ?? []

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <div>
          <h1 className='text-2xl font-bold tracking-tight'>任务</h1>
          <p className='text-sm text-muted-foreground'>
            到点后由后端无人值守地跑完一轮 Agent 对话；调度精度为秒级到十秒级，
            系统停机期间错过的触发点不会补跑。
          </p>
        </div>
        <Button onClick={() => setEditing(null)} disabled={!activePlatformId}>
          <Plus className='mr-1 size-4' /> 新建任务
        </Button>
      </div>

      <div className='flex flex-wrap items-center gap-2'>
        <Select
          value={activePlatformId?.toString() ?? ''}
          onValueChange={(value) => setPlatformId(Number(value))}
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

        <Select value={statusFilter} onValueChange={setStatusFilter}>
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
          onClick={() => tasksQuery.refetch()}
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
              <th className='p-3 font-medium'>触发</th>
              <th className='p-3 font-medium'>下次运行</th>
              <th className='p-3 font-medium'>状态</th>
              <th className='p-3 text-right font-medium'>操作</th>
            </tr>
          </thead>
          <tbody>
            {tasksQuery.isLoading && (
              <tr>
                <td className='p-3 text-muted-foreground' colSpan={5}>
                  加载中...
                </td>
              </tr>
            )}
            {!tasksQuery.isLoading && tasks.length === 0 && (
              <tr>
                <td className='p-3 text-muted-foreground' colSpan={5}>
                  暂无任务
                </td>
              </tr>
            )}
            {tasks.map((task) => (
              <tr key={task.id} className='border-t'>
                <td className='p-3'>
                  <Link
                    to='/tasks/$taskId'
                    params={{ taskId: String(task.id) }}
                    search={{ platform: activePlatformId }}
                    className='font-medium hover:underline'
                  >
                    {task.name}
                  </Link>
                  {task.created_by_type === 'agent' && (
                    <Badge variant='outline' className='ml-2'>
                      智能体创建
                    </Badge>
                  )}
                </td>
                <td className='p-3 text-muted-foreground'>
                  {task.trigger_type === 'cron'
                    ? task.cron_expression
                    : `一次性 ${task.run_at ? formatDateTime(task.run_at) : ''}`}
                  <span className='ml-1 text-xs'>({task.timezone})</span>
                </td>
                <td className='p-3 text-muted-foreground'>
                  {task.next_run_at ? formatDateTime(task.next_run_at) : '—'}
                </td>
                <td className='p-3'>
                  <Badge
                    variant={STATUS_LABEL[task.status]?.variant ?? 'secondary'}
                  >
                    {STATUS_LABEL[task.status]?.text ?? task.status}
                  </Badge>
                </td>
                <td className='p-3 text-right'>
                  <div className='flex justify-end gap-1'>
                    <Button
                      size='sm'
                      variant='outline'
                      onClick={() => runMutation.mutate(task)}
                      disabled={runMutation.isPending}
                    >
                      立即运行
                    </Button>
                    <Button
                      size='sm'
                      variant='outline'
                      onClick={() => toggleMutation.mutate(task)}
                    >
                      {task.status === 'active' ? '暂停' : '启用'}
                    </Button>
                    <Button
                      size='sm'
                      variant='outline'
                      onClick={() => setEditing(task)}
                    >
                      编辑
                    </Button>
                    <Button
                      size='sm'
                      variant='destructive'
                      onClick={() => setDeleting(task)}
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

      <TaskDialog
        key={editing?.id ?? 'new'}
        task={editing ?? null}
        open={editing !== undefined}
        onOpenChange={(open) => {
          if (!open) setEditing(undefined)
        }}
        agents={agentsQuery.data?.items ?? []}
        isSaving={saveMutation.isPending}
        onSubmit={(values) => saveMutation.mutate(values)}
      />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null)
        }}
        title='删除任务'
        desc={`确定要删除任务「${deleting?.name ?? ''}」吗？该任务的执行记录会一并删除，它创建过的会话会保留。`}
        confirmText='删除'
        destructive
        isLoading={deleteMutation.isPending}
        handleConfirm={() => deleting && deleteMutation.mutate(deleting)}
      />
    </div>
  )
}

/** 把表单值转换成接口入参；未选中的触发字段显式置空，避免残留旧值。 */
function toTaskInput(values: TaskForm): TaskInput {
  const isCron = values.trigger_type === 'cron'
  return {
    name: values.name,
    prompt: values.prompt,
    agent_id: values.agent_id,
    trigger_type: values.trigger_type,
    cron_expression: isCron ? values.cron_expression : null,
    run_at: isCron ? null : toIsoOrNull(values.run_at),
    timezone: values.timezone,
    auto_approve: values.auto_approve,
    strict_approval: values.strict_approval,
    timeout_seconds: values.timeout_seconds,
  }
}

/** datetime-local 的值没有时区，交给后端按任务时区解释；这里只做空值归一。 */
function toIsoOrNull(value?: string): string | null {
  const trimmed = (value ?? '').trim()
  return trimmed.length > 0 ? trimmed : null
}

function TaskDialog({
  task,
  open,
  onOpenChange,
  agents,
  isSaving,
  onSubmit,
}: {
  task: Task | null
  open: boolean
  onOpenChange: (open: boolean) => void
  agents: { id: number; name: string }[]
  isSaving: boolean
  onSubmit: (values: TaskForm) => void
}) {
  const form = useForm<TaskForm>({
    resolver: zodResolver(taskSchema),
    values: {
      name: task?.name ?? '',
      prompt: task?.prompt ?? '',
      agent_id: task?.agent_id ?? 0,
      trigger_type: task?.trigger_type ?? 'cron',
      cron_expression: task?.cron_expression ?? '0 9 * * *',
      run_at: task?.run_at ? task.run_at.slice(0, 16) : '',
      timezone: task?.timezone ?? 'Asia/Shanghai',
      auto_approve: task?.auto_approve ?? true,
      strict_approval: task?.strict_approval ?? false,
      timeout_seconds: task?.timeout_seconds ?? 600,
    },
  })
  const triggerType = form.watch('trigger_type')

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-h-[90vh] max-w-2xl overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>{task ? '编辑任务' : '新建任务'}</DialogTitle>
          <DialogDescription>
            任务会无人值守地自动运行，执行期间没有人可以确认操作。
          </DialogDescription>
        </DialogHeader>
        <form
          id='task-form'
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
            <Label>智能体</Label>
            <Select
              value={
                form.watch('agent_id') ? String(form.watch('agent_id')) : ''
              }
              onValueChange={(value) =>
                form.setValue('agent_id', Number(value), {
                  shouldValidate: true,
                })
              }
            >
              <SelectTrigger>
                <SelectValue placeholder='选择要运行的智能体' />
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
            <Label>指令</Label>
            <Textarea
              rows={4}
              placeholder='到点后发给智能体的完整指令，例如：检查今日订单异常并汇总'
              {...form.register('prompt')}
            />
            <p className='mt-1 text-xs text-destructive'>
              {form.formState.errors.prompt?.message}
            </p>
            <p className='mt-1 text-xs text-muted-foreground'>
              每次运行都是新会话，指令要写成独立可执行的完整句子。
            </p>
          </div>

          <div className='grid gap-3 sm:grid-cols-2'>
            <div>
              <Label>触发类型</Label>
              <Select
                value={triggerType}
                onValueChange={(value) =>
                  form.setValue('trigger_type', value as 'cron' | 'once')
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value='cron'>周期（cron）</SelectItem>
                  <SelectItem value='once'>一次性</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label>时区</Label>
              <Select
                value={form.watch('timezone')}
                onValueChange={(value) => form.setValue('timezone', value)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TIMEZONES.map((tz) => (
                    <SelectItem key={tz} value={tz}>
                      {tz}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {triggerType === 'cron' ? (
              <div className='sm:col-span-2'>
                <Label>触发规则</Label>
                <div className='flex flex-wrap gap-2'>
                  {TRIGGER_PRESETS.map((preset) => (
                    <Button
                      key={preset.value}
                      type='button'
                      size='sm'
                      variant='outline'
                      onClick={() => {
                        if (preset.cron)
                          form.setValue('cron_expression', preset.cron)
                      }}
                    >
                      {preset.label}
                    </Button>
                  ))}
                </div>
                <Input
                  className='mt-2 font-mono'
                  placeholder='分 时 日 月 周，例如 0 9 * * *'
                  {...form.register('cron_expression')}
                />
                <p className='mt-1 text-xs text-destructive'>
                  {form.formState.errors.cron_expression?.message}
                </p>
                <p className='mt-1 text-xs text-muted-foreground'>
                  五段式 cron，最小间隔 1 分钟；下一次运行时间以后端计算为准。
                </p>
              </div>
            ) : (
              <div className='sm:col-span-2'>
                <Label>执行时间</Label>
                <Input type='datetime-local' {...form.register('run_at')} />
                <p className='mt-1 text-xs text-destructive'>
                  {form.formState.errors.run_at?.message}
                </p>
              </div>
            )}
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
                checked={form.watch('auto_approve')}
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
                checked={form.watch('strict_approval')}
                onCheckedChange={(value) =>
                  form.setValue('strict_approval', value)
                }
              />
            </div>
            <div>
              <Label>单次执行超时（秒）</Label>
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
          <Button type='submit' form='task-form' disabled={isSaving}>
            {isSaving ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export { RUN_STATUS_LABEL }
