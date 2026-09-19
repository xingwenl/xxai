import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { ArrowLeft } from 'lucide-react'
import { toast } from 'sonner'
import {
  getTask,
  getTaskRunDetail,
  listTaskRuns,
  runTaskNow,
  type TaskRun,
  type TaskRunDetail,
} from '@/api/task'
import { formatDateTime } from '@/lib/time'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

const routeApi = getRouteApi('/_authenticated/tasks/$taskId')

const RUN_STATUS_VARIANT: Record<
  string,
  { text: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }
> = {
  running: { text: '执行中', variant: 'default' },
  completed: { text: '已完成', variant: 'outline' },
  failed: { text: '失败', variant: 'destructive' },
  skipped: { text: '已跳过', variant: 'secondary' },
}

const SKIP_REASON_TEXT: Record<string, string> = {
  overlapped: '上一次运行尚未结束',
  task_paused: '任务已暂停',
  deadline_missed: '错过触发点（不补跑）',
}

export function TaskDetailPage() {
  const { taskId } = routeApi.useParams()
  const search = routeApi.useSearch()
  const navigate = routeApi.useNavigate()
  const queryClient = useQueryClient()
  const taskIdNumber = Number(taskId)
  const platformId = search.platform
  const tab = search.tab ?? 'overview'

  const [runPage, setRunPage] = useState(1)

  const taskQuery = useQuery({
    queryKey: ['task', platformId, taskIdNumber],
    queryFn: () => getTask(platformId!, taskIdNumber),
    enabled: platformId != null && Number.isFinite(taskIdNumber),
  })

  const runsQuery = useQuery({
    queryKey: ['task-runs', platformId, taskIdNumber, runPage],
    queryFn: () =>
      listTaskRuns(platformId!, taskIdNumber, { page: runPage, pageSize: 20 }),
    enabled:
      platformId != null && Number.isFinite(taskIdNumber) && tab === 'runs',
  })

  const runMutation = useMutation({
    mutationFn: () => runTaskNow(platformId!, taskIdNumber),
    onSuccess: async (data) => {
      toast.success(data.message)
      await queryClient.invalidateQueries({
        queryKey: ['task-runs', platformId, taskIdNumber],
      })
      await queryClient.invalidateQueries({
        queryKey: ['task', platformId, taskIdNumber],
      })
    },
  })

  const task = taskQuery.data

  if (platformId == null) {
    return (
      <div className='p-6 text-sm text-muted-foreground'>
        缺少平台参数，请从任务列表进入。
        <Link to='/tasks' className='ml-2 underline'>
          返回列表
        </Link>
      </div>
    )
  }

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <div className='flex items-center gap-3'>
          <Button variant='outline' size='icon' asChild aria-label='返回'>
            <Link to='/tasks'>
              <ArrowLeft className='size-4' />
            </Link>
          </Button>
          <div>
            <h1 className='text-2xl font-bold tracking-tight'>
              {task?.name ?? '任务详情'}
            </h1>
            <p className='text-sm text-muted-foreground'>
              {task
                ? `下次运行：${task.next_run_at ? formatDateTime(task.next_run_at) : '不再触发'}`
                : ''}
            </p>
          </div>
        </div>
        <Button
          onClick={() => runMutation.mutate()}
          disabled={runMutation.isPending}
        >
          {runMutation.isPending ? '提交中...' : '立即运行一次'}
        </Button>
      </div>

      <Tabs
        value={tab}
        onValueChange={(value) =>
          navigate({
            search: { platform: platformId, tab: value as 'overview' | 'runs' },
          })
        }
      >
        <TabsList>
          <TabsTrigger value='overview'>概览</TabsTrigger>
          <TabsTrigger value='runs'>执行历史</TabsTrigger>
        </TabsList>

        <TabsContent value='overview' className='mt-4'>
          {taskQuery.isLoading && (
            <p className='text-sm text-muted-foreground'>加载中...</p>
          )}
          {task && (
            <dl className='grid gap-4 sm:grid-cols-2'>
              <DetailItem label='状态'>
                <Badge
                  variant={task.status === 'active' ? 'default' : 'secondary'}
                >
                  {task.status === 'active' ? '启用' : '暂停'}
                </Badge>
              </DetailItem>
              <DetailItem label='触发规则'>
                {task.trigger_type === 'cron'
                  ? `${task.cron_expression}（${task.timezone}）`
                  : `一次性 ${task.run_at ? formatDateTime(task.run_at) : ''}`}
              </DetailItem>
              <DetailItem label='上次运行'>
                {task.last_run_at ? formatDateTime(task.last_run_at) : '—'}
              </DetailItem>
              <DetailItem label='单次超时'>
                {task.timeout_seconds} 秒
              </DetailItem>
              <DetailItem label='自动批准工具'>
                {task.auto_approve ? '开启' : '关闭'}
                {task.strict_approval ? '（严格模式：仅页面跳转类）' : ''}
              </DetailItem>
              <DetailItem label='创建方式'>
                {task.created_by_type === 'agent' ? '智能体创建' : '用户创建'}
              </DetailItem>
              <DetailItem label='指令' className='sm:col-span-2'>
                <pre className='overflow-x-auto rounded-md bg-muted p-3 text-xs whitespace-pre-wrap'>
                  {task.prompt}
                </pre>
              </DetailItem>
            </dl>
          )}
        </TabsContent>

        <TabsContent value='runs' className='mt-4'>
          <div className='rounded-md border'>
            <table className='w-full text-sm'>
              <thead className='bg-muted/50 text-left text-muted-foreground'>
                <tr>
                  <th className='p-3 font-medium'>状态</th>
                  <th className='p-3 font-medium'>触发方式</th>
                  <th className='p-3 font-medium'>开始时间</th>
                  <th className='p-3 font-medium'>结束时间</th>
                  <th className='p-3 font-medium'>自动批准</th>
                  <th className='p-3 font-medium'>详情</th>
                </tr>
              </thead>
              <tbody>
                {runsQuery.isLoading && (
                  <tr>
                    <td className='p-3 text-muted-foreground' colSpan={6}>
                      加载中...
                    </td>
                  </tr>
                )}
                {!runsQuery.isLoading &&
                  (runsQuery.data?.items.length ?? 0) === 0 && (
                    <tr>
                      <td className='p-3 text-muted-foreground' colSpan={6}>
                        暂无执行记录
                      </td>
                    </tr>
                  )}
                {(runsQuery.data?.items ?? []).map((run) => (
                  <RunRows
                    key={run.id}
                    run={run}
                    platformId={platformId}
                    taskId={taskIdNumber}
                  />
                ))}
              </tbody>
            </table>
          </div>

          <div className='mt-3 flex items-center justify-between'>
            <span className='text-xs text-muted-foreground'>
              共 {runsQuery.data?.total ?? 0} 条
            </span>
            <div className='flex gap-2'>
              <Button
                size='sm'
                variant='outline'
                disabled={runPage <= 1}
                onClick={() => setRunPage((page) => Math.max(1, page - 1))}
              >
                上一页
              </Button>
              <Button
                size='sm'
                variant='outline'
                disabled={runPage >= (runsQuery.data?.totalPage ?? 1)}
                onClick={() => setRunPage((page) => page + 1)}
              >
                下一页
              </Button>
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}

function DetailItem({
  label,
  children,
  className,
}: {
  label: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={className}>
      <dt className='text-xs text-muted-foreground'>{label}</dt>
      <dd className='mt-1 text-sm'>{children}</dd>
    </div>
  )
}

/**
 * 一条执行记录 + 可展开的执行过程。
 *
 * 展开时按需拉取该次运行的步骤（思考、工具调用、结果、错误），
 * 用于排查「为什么超时/失败」——先看最后停在哪一步。
 */
function RunRows({
  run,
  platformId,
  taskId,
}: {
  run: TaskRun
  platformId: number
  taskId: number
}) {
  const [expanded, setExpanded] = useState(false)
  const canExpand = run.agent_loop_run_id != null || run.status === 'failed'

  const detailQuery = useQuery({
    queryKey: ['task-run-detail', platformId, taskId, run.id],
    queryFn: () => getTaskRunDetail(platformId, taskId, run.id),
    enabled: expanded && canExpand,
  })

  return (
    <>
      <tr className='border-t'>
        <td className='p-3'>
          <Badge
            variant={RUN_STATUS_VARIANT[run.status]?.variant ?? 'secondary'}
          >
            {RUN_STATUS_VARIANT[run.status]?.text ?? run.status}
          </Badge>
        </td>
        <td className='text-muted-foreground p-3'>
          {run.trigger_kind === 'manual' ? '手动' : '到点'}
        </td>
        <td className='text-muted-foreground p-3'>
          {run.started_at ? formatDateTime(run.started_at) : '—'}
        </td>
        <td className='text-muted-foreground p-3'>
          {run.finished_at ? formatDateTime(run.finished_at) : '—'}
        </td>
        <td className='text-muted-foreground p-3'>
          {run.auto_approved_count}
        </td>
        <td className='p-3'>
          <div className='flex items-center gap-3'>
            {canExpand && (
              <button
                type='button'
                onClick={() => setExpanded((value) => !value)}
                className='text-xs underline'
              >
                {expanded ? '收起过程' : '查看过程'}
              </button>
            )}
            <RunDetail run={run} />
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className='bg-muted/30'>
          <td className='p-3' colSpan={6}>
            <RunSteps
              isLoading={detailQuery.isLoading}
              detail={detailQuery.data}
              run={run}
            />
          </td>
        </tr>
      )}
    </>
  )
}

/** 执行过程的步骤清单。 */
function RunSteps({
  isLoading,
  detail,
  run,
}: {
  isLoading: boolean
  detail?: TaskRunDetail
  run: TaskRun
}) {
  if (isLoading) {
    return <p className='text-muted-foreground text-xs'>加载执行过程...</p>
  }

  const steps = detail?.steps ?? []

  if (steps.length === 0) {
    // 没有步骤通常是「从未真正执行」——这正是排查超时时最需要区分的情况
    return (
      <div className='text-xs'>
        <p className='text-muted-foreground'>
          没有执行步骤记录。
          {run.status === 'failed' && !run.conversation_id
            ? '这次运行没有创建会话，说明它可能从未真正开始执行（例如排队后未被调度器认领）。'
            : ''}
        </p>
        {run.error_message && (
          <p className='text-destructive mt-1'>错误：{run.error_message}</p>
        )}
      </div>
    )
  }

  return (
    <div className='flex flex-col gap-2 text-xs'>
      {detail?.loop_summary && (
        <p className='text-muted-foreground'>概要：{detail.loop_summary}</p>
      )}
      {steps.map((step) => (
        <div key={step.id} className='rounded-md border bg-background p-2'>
          <div className='flex flex-wrap items-center gap-2'>
            <span className='text-muted-foreground'>#{step.sequence}</span>
            <span className='font-medium'>{step.title ?? step.step_type}</span>
            <Badge
              variant={step.status === 'failed' ? 'destructive' : 'outline'}
            >
              {step.status ?? '—'}
            </Badge>
            {step.tool_name && (
              <span className='text-muted-foreground'>工具：{step.tool_name}</span>
            )}
            {step.skill_name && (
              <span className='text-muted-foreground'>技能：{step.skill_name}</span>
            )}
          </div>
          {step.thinking_text && (
            <p className='text-muted-foreground mt-1 whitespace-pre-wrap'>
              思考：{step.thinking_text}
            </p>
          )}
          {step.output_summary && (
            <p className='mt-1 break-all whitespace-pre-wrap'>
              结果：{step.output_summary}
            </p>
          )}
          {step.error && <p className='text-destructive mt-1'>错误：{step.error}</p>}
        </div>
      ))}
      {run.error_message && (
        <p className='text-destructive'>运行错误：{run.error_message}</p>
      )}
    </div>
  )
}

/** 执行记录详情：失败原因、跳过原因，以及可跳转到对应会话的入口。 */
function RunDetail({ run }: { run: TaskRun }) {
  if (run.status === 'skipped') {
    return (
      <span className='text-xs text-muted-foreground'>
        {SKIP_REASON_TEXT[run.skip_reason ?? ''] ?? run.skip_reason ?? '已跳过'}
      </span>
    )
  }
  if (run.status === 'failed') {
    return (
      <span className='text-xs text-destructive'>
        {run.error_message ?? '失败'}
      </span>
    )
  }
  if (run.conversation_id != null) {
    // chats 路由已支持 ?conversation=<id> 直接定位会话。
    return (
      <Link
        to='/chats'
        search={{ conversation: run.conversation_id }}
        className='text-xs underline'
      >
        查看会话 #{run.conversation_id}
      </Link>
    )
  }
  return <span className='text-xs text-muted-foreground'>—</span>
}
