import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { ArrowLeft } from 'lucide-react'
import { toast } from 'sonner'
import { listAgents } from '@/api/agent'
import {
  getWorkflow,
  getWorkflowRunDetail,
  listWorkflowRuns,
  runWorkflowNow,
  updateWorkflow,
  type WorkflowRun,
  type WorkflowRunDetail,
  type WorkflowStepRun,
  type WorkflowUpdate,
} from '@/api/workflow'
import { formatDateTime } from '@/lib/time'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { dagShape } from '@/features/workflows/workflow-dag'
import { WorkflowDefinitionForm } from '@/features/workflows/workflow-definition-form'

const routeApi = getRouteApi('/_authenticated/workflows/$workflowId')

const RUN_STATUS_VARIANT: Record<
  string,
  { text: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }
> = {
  running: { text: '执行中', variant: 'default' },
  completed: { text: '已完成', variant: 'outline' },
  failed: { text: '失败', variant: 'destructive' },
  skipped: { text: '已跳过', variant: 'secondary' },
}

const STEP_STATUS_VARIANT: Record<
  string,
  { text: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }
> = {
  running: { text: '执行中', variant: 'default' },
  succeeded: { text: '成功', variant: 'outline' },
  failed: { text: '失败', variant: 'destructive' },
  skipped: { text: '已跳过', variant: 'secondary' },
  waiting: { text: '等待中', variant: 'secondary' },
}

const SKIP_REASON_TEXT: Record<string, string> = {
  overlapped: '上一次运行尚未结束',
  workflow_paused: '工作流已暂停',
  deadline_missed: '错过触发点（不补跑）',
}

export function WorkflowDetailPage() {
  const { workflowId } = routeApi.useParams()
  const search = routeApi.useSearch()
  const navigate = routeApi.useNavigate()
  const queryClient = useQueryClient()
  const workflowIdNumber = Number(workflowId)
  const platformId = search.platform
  const tab = search.tab ?? 'definition'

  const [runPage, setRunPage] = useState(1)

  const workflowQuery = useQuery({
    queryKey: ['workflow', platformId, workflowIdNumber],
    queryFn: () => getWorkflow(platformId!, workflowIdNumber),
    enabled: platformId != null && Number.isFinite(workflowIdNumber),
  })

  const agentsQuery = useQuery({
    queryKey: ['agents', platformId],
    queryFn: () => listAgents(platformId!, { pageSize: 100 }),
    enabled: platformId != null,
  })

  const runsQuery = useQuery({
    queryKey: ['workflow-runs', platformId, workflowIdNumber, runPage],
    queryFn: () =>
      listWorkflowRuns(platformId!, workflowIdNumber, {
        page: runPage,
        pageSize: 20,
      }),
    enabled:
      platformId != null && Number.isFinite(workflowIdNumber) && tab === 'runs',
  })

  const saveMutation = useMutation({
    mutationFn: (input: WorkflowUpdate) =>
      updateWorkflow(platformId!, workflowIdNumber, input),
    onSuccess: async () => {
      toast.success('工作流定义已保存')
      await queryClient.invalidateQueries({
        queryKey: ['workflow', platformId, workflowIdNumber],
      })
      await queryClient.invalidateQueries({ queryKey: ['workflows'] })
    },
  })

  const runMutation = useMutation({
    mutationFn: () => runWorkflowNow(platformId!, workflowIdNumber),
    onSuccess: async (data) => {
      toast.success(data.message)
      // 接口只负责排队，运行列表要自己刷新才能看到新建的 running 记录。
      await queryClient.invalidateQueries({
        queryKey: ['workflow-runs', platformId, workflowIdNumber],
      })
      await queryClient.invalidateQueries({
        queryKey: ['workflow-latest-run', platformId, workflowIdNumber],
      })
    },
  })

  const toggleMutation = useMutation({
    mutationFn: (status: 'active' | 'paused') =>
      updateWorkflow(platformId!, workflowIdNumber, { status }),
    onSuccess: async (workflow) => {
      toast.success(
        workflow.status === 'active' ? '工作流已启用' : '工作流已暂停'
      )
      await queryClient.invalidateQueries({
        queryKey: ['workflow', platformId, workflowIdNumber],
      })
      await queryClient.invalidateQueries({ queryKey: ['workflows'] })
    },
  })

  if (platformId == null) {
    return (
      <div className='p-6 text-sm text-muted-foreground'>
        缺少平台参数，请从工作流列表进入。
        <Link to='/workflows' className='ml-2 underline'>
          返回列表
        </Link>
      </div>
    )
  }

  const workflow = workflowQuery.data

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <div className='flex items-center gap-3'>
          <Button variant='outline' size='icon' asChild aria-label='返回'>
            <Link to='/workflows'>
              <ArrowLeft className='size-4' />
            </Link>
          </Button>
          <div>
            <h1 className='flex items-center gap-2 text-2xl font-bold tracking-tight'>
              {workflow?.name ?? '工作流详情'}
              {workflow && (
                <Badge
                  variant={
                    workflow.status === 'active' ? 'default' : 'secondary'
                  }
                >
                  {workflow.status === 'active' ? '启用' : '暂停'}
                </Badge>
              )}
            </h1>
            <p className='text-sm text-muted-foreground'>
              {workflow
                ? `版本 v${workflow.version} · ${workflow.steps.length} 个步骤 · ${dagShape(workflow.steps).layers} 个并行层（最宽 ${dagShape(workflow.steps).maxWidth}） · 整条超时 ${workflow.timeout_seconds} 秒`
                : ''}
            </p>
          </div>
        </div>
        <div className='flex gap-2'>
          {workflow && (
            <Button
              variant='outline'
              onClick={() =>
                toggleMutation.mutate(
                  workflow.status === 'active' ? 'paused' : 'active'
                )
              }
              disabled={toggleMutation.isPending}
            >
              {workflow.status === 'active' ? '暂停' : '启用'}
            </Button>
          )}
          <Button
            onClick={() => runMutation.mutate()}
            disabled={runMutation.isPending}
          >
            {runMutation.isPending ? '提交中...' : '立即运行'}
          </Button>
        </div>
      </div>

      <Tabs
        value={tab}
        onValueChange={(value) =>
          navigate({
            search: {
              platform: platformId,
              tab: value as 'definition' | 'runs',
            },
          })
        }
      >
        <TabsList>
          <TabsTrigger value='definition'>定义</TabsTrigger>
          <TabsTrigger value='runs'>运行记录</TabsTrigger>
        </TabsList>

        <TabsContent value='definition' className='mt-4'>
          {workflowQuery.isLoading && (
            <p className='text-sm text-muted-foreground'>加载中...</p>
          )}
          {workflow && (
            <WorkflowDefinitionForm
              // 保存成功后 version 会 +1，用版本号做 key 让表单重新按新定义初始化。
              key={`${workflow.id}-${workflow.version}`}
              workflow={workflow}
              agents={agentsQuery.data?.items ?? []}
              isSaving={saveMutation.isPending}
              onSubmit={(input) => saveMutation.mutate(input)}
            />
          )}
        </TabsContent>

        <TabsContent value='runs' className='mt-4'>
          <div className='rounded-md border'>
            <table className='w-full text-sm'>
              <thead className='bg-muted/50 text-left text-muted-foreground'>
                <tr>
                  <th className='p-3 font-medium'>状态</th>
                  <th className='p-3 font-medium'>触发方式</th>
                  <th className='p-3 font-medium'>版本</th>
                  <th className='p-3 font-medium'>开始时间</th>
                  <th className='p-3 font-medium'>结束时间</th>
                  <th className='p-3 font-medium'>步数</th>
                  <th className='p-3 font-medium'>说明</th>
                  <th className='p-3 font-medium'>明细</th>
                </tr>
              </thead>
              <tbody>
                {runsQuery.isLoading && (
                  <tr>
                    <td className='p-3 text-muted-foreground' colSpan={8}>
                      加载中...
                    </td>
                  </tr>
                )}
                {!runsQuery.isLoading &&
                  (runsQuery.data?.items.length ?? 0) === 0 && (
                    <tr>
                      <td className='p-3 text-muted-foreground' colSpan={8}>
                        暂无运行记录
                      </td>
                    </tr>
                  )}
                {(runsQuery.data?.items ?? []).map((run) => (
                  <RunRows
                    key={run.id}
                    run={run}
                    platformId={platformId}
                    workflowId={workflowIdNumber}
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

/**
 * 一条运行记录 + 可展开的每步明细。
 *
 * 展开时才按需拉取该次运行的步骤（不含定义快照），
 * 用于回答「是哪一步失败、有没有用兜底值、模型最终看到了什么」。
 */
function RunRows({
  run,
  platformId,
  workflowId,
}: {
  run: WorkflowRun
  platformId: number
  workflowId: number
}) {
  const [expanded, setExpanded] = useState(false)

  const detailQuery = useQuery({
    queryKey: ['workflow-run-detail', platformId, workflowId, run.id],
    queryFn: () => getWorkflowRunDetail(platformId, workflowId, run.id),
    enabled: expanded,
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
        <td className='p-3 text-muted-foreground'>
          {run.trigger_kind === 'manual' ? '手动' : '定时'}
        </td>
        <td className='p-3 text-muted-foreground'>
          v{run.definition_version_id}
        </td>
        <td className='p-3 text-muted-foreground'>
          {run.started_at ? formatDateTime(run.started_at) : '—'}
        </td>
        <td className='p-3 text-muted-foreground'>
          {run.finished_at ? formatDateTime(run.finished_at) : '—'}
        </td>
        <td className='p-3 text-muted-foreground'>
          {run.completed_steps} / {run.total_steps}
        </td>
        <td className='p-3'>
          <RunSummary run={run} />
        </td>
        <td className='p-3'>
          <button
            type='button'
            onClick={() => setExpanded((value) => !value)}
            className='text-xs underline'
          >
            {expanded ? '收起明细' : '查看明细'}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className='bg-muted/30'>
          <td className='p-3' colSpan={8}>
            <StepRuns
              isLoading={detailQuery.isLoading}
              detail={detailQuery.data}
              platformId={platformId}
            />
          </td>
        </tr>
      )}
    </>
  )
}

/** 运行记录的简述：跳过原因、失败原因，或自动批准次数。 */
function RunSummary({ run }: { run: WorkflowRun }) {
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
  return (
    <span className='text-xs text-muted-foreground'>
      自动批准 {run.auto_approved_count} 次
    </span>
  )
}

/** 每步明细：序号、step_id、类型、状态、兜底标记、错误与模型可见输出。 */
function StepRuns({
  isLoading,
  detail,
  platformId,
}: {
  isLoading: boolean
  detail?: WorkflowRunDetail
  platformId: number
}) {
  if (isLoading) {
    return <p className='text-xs text-muted-foreground'>加载步骤明细...</p>
  }

  const steps = detail?.steps ?? []

  if (steps.length === 0) {
    // 没有步骤记录是最需要区分的情况：运行可能排队后从未被真正认领。
    return (
      <div className='text-xs text-muted-foreground'>
        <p>没有步骤记录。</p>
        {detail?.run.error_message && (
          <p className='mt-1 text-destructive'>
            错误：{detail.run.error_message}
          </p>
        )}
      </div>
    )
  }

  return (
    <div className='flex flex-col gap-2 text-xs'>
      {steps.map((step) => (
        <StepRunCard key={step.id} step={step} platformId={platformId} />
      ))}
    </div>
  )
}

function StepRunCard({
  step,
  platformId,
}: {
  step: WorkflowStepRun
  platformId: number
}) {
  return (
    <div className='rounded-md border bg-background p-2'>
      <div className='flex flex-wrap items-center gap-2'>
        <span className='text-muted-foreground'>#{step.seq}</span>
        <span className='font-medium'>{step.step_id}</span>
        <Badge variant='outline'>
          {step.node_type === 'agent'
            ? 'Agent'
            : step.node_type === 'condition'
              ? '条件'
              : '工具'}
        </Badge>
        <Badge
          variant={STEP_STATUS_VARIANT[step.status]?.variant ?? 'secondary'}
        >
          {STEP_STATUS_VARIANT[step.status]?.text ?? step.status}
        </Badge>
        {step.on_error_applied && (
          <Badge variant='secondary'>已使用兜底输出</Badge>
        )}
        {step.retry_count > 1 && (
          // retry_count 是实际尝试次数（首跑成功记 1），只有真的重试过才值得显示。
          <span className='text-muted-foreground'>
            尝试 {step.retry_count} 次
          </span>
        )}
        <span className='text-muted-foreground'>
          {step.started_at ? formatDateTime(step.started_at) : ''}
          {step.finished_at ? ` → ${formatDateTime(step.finished_at)}` : ''}
        </span>
        {step.conversation_id != null && (
          // 会话记录页的第三层直接展示这条会话的消息与 Agent 过程（带平台参数以定位租户）。
          <Link
            to='/conversations/$conversationId'
            params={{ conversationId: String(step.conversation_id) }}
            search={{ platform: platformId }}
            className='underline'
          >
            查看会话 #{step.conversation_id}
          </Link>
        )}
      </div>

      {step.error_message && (
        <p className='mt-1 text-destructive'>错误：{step.error_message}</p>
      )}

      {step.model_visible_output && (
        <div className='mt-1'>
          <p className='text-muted-foreground'>
            模型可见输出
            {step.output_truncated
              ? `（超过 50KB 已截断，完整输出 ${step.raw_output_size} 字节）`
              : `（${step.raw_output_size} 字节）`}
          </p>
          <pre className='mt-1 overflow-x-auto rounded-md bg-muted p-2 whitespace-pre-wrap'>
            {step.model_visible_output}
          </pre>
        </div>
      )}
    </div>
  )
}
