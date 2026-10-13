import { http } from '@/lib/http'

/** 工作流步骤类型：agent 跑一轮 Agent 对话，tool 直接调用一个工具。 */
export type WorkflowStepKind = 'agent' | 'tool'

/** 步骤失败策略：abort 中止整条工作流；continue_with_default 用兜底输出继续；fail_branch 为预留值（v1 暂未实现）。 */
export type WorkflowStepOnError =
  | 'abort'
  | 'continue_with_default'
  | 'fail_branch'

/** 工作流步骤：有序执行单元。kind=agent 跑一轮 Agent，kind=tool 直接调一个工具。 */
export type WorkflowStep = {
  /** 稳定字符串标识（非自增），后续步骤用它引用本步输出 */
  step_id: string
  name: string
  kind: WorkflowStepKind
  /** kind=agent 时可选：覆盖工作流级 Agent（必须同平台） */
  agent_id: number | null
  /** kind=agent 时的指令；可写 {{step_id.path}} 引用前序步骤输出 */
  prompt: string | null
  /** kind=tool 时的工具名 */
  tool_name: string | null
  /** kind=tool 时的参数模板，值里可写 {{step_id.path}} */
  tool_arguments: Record<string, unknown> | null
  /** 输入绑定：{参数名: [前序 step_id, 输出路径]}；路径取 "output" 表示该步模型可见输出 */
  input_bindings: Record<string, [string, string]>
  on_error: WorkflowStepOnError
  /** on_error=continue_with_default 时使用的兜底输出 */
  default_output: string | null
  timeout_seconds: number | null
}

/** 工作流：一串按固定顺序执行的步骤定义 + 工作流级默认 Agent 与审批策略。 */
export type Workflow = {
  id: number
  platform_id: number
  name: string
  description: string | null
  agent_id: number
  owner_user_id: number | null
  status: 'active' | 'paused'
  /** 每次保存 +1 */
  version: number
  max_steps: number
  steps: WorkflowStep[]
  timeout_seconds: number
  auto_approve: boolean
  strict_approval: boolean
  created_by_type: string
  created_by_user_id: number | null
  created_by_agent_id: number | null
  created_at: string
  updated_at: string
}

/** 写入用的步骤：step_id / name / kind / on_error 必填，其余字段按 kind 选择性提供。 */
export type WorkflowStepWrite = Pick<
  WorkflowStep,
  'step_id' | 'name' | 'kind' | 'on_error'
> &
  Partial<Omit<WorkflowStep, 'step_id' | 'name' | 'kind' | 'on_error'>>

export type WorkflowCreate = {
  name: string
  description?: string | null
  agent_id: number
  max_steps?: number
  steps: WorkflowStepWrite[]
  timeout_seconds?: number
  auto_approve?: boolean
  strict_approval?: boolean
}

export type WorkflowUpdate = Partial<WorkflowCreate> & {
  status?: 'active' | 'paused'
}

/** 工作流运行：工作流的一次完整执行记录（含被跳过的触发点）。 */
export type WorkflowRun = {
  id: number
  workflow_id: number
  definition_version_id: number
  status: 'running' | 'completed' | 'failed' | 'skipped'
  trigger_kind: 'manual' | 'scheduled'
  run_as_type: string
  run_as_user_id: number | null
  run_as_end_user_id: number | null
  planned_at: string | null
  started_at: string | null
  finished_at: string | null
  error_message: string | null
  /** overlapped / workflow_paused / deadline_missed */
  skip_reason: string | null
  auto_approved_count: number
  total_steps: number
  completed_steps: number
  created_at: string
  updated_at: string
}

/** 步骤运行：某次运行里一步的执行记录。 */
export type WorkflowStepRun = {
  id: number
  run_id: number
  step_id: string
  seq: number
  node_type: 'agent' | 'tool'
  status: 'running' | 'succeeded' | 'failed' | 'skipped' | 'waiting'
  retry_count: number
  /** 该步失败后是否用了兜底值（on_error=continue_with_default 生效时为 true） */
  on_error_applied: boolean
  error_message: string | null
  conversation_id: number | null
  agent_loop_run_id: number | null
  /** 进下一步的模型可见输出（超 50KB 已截断并带标记） */
  model_visible_output: string | null
  /** 完整输出字节数 */
  raw_output_size: number
  output_truncated: boolean
  started_at: string | null
  finished_at: string | null
}

/** 单次运行的步骤明细。 */
export type WorkflowRunDetail = {
  run: WorkflowRun
  steps: WorkflowStepRun[]
}

export type WorkflowPage = {
  items: Workflow[]
  total: number
  page: number
  pageSize: number
  totalPage: number
}

export type WorkflowRunPage = {
  items: WorkflowRun[]
  total: number
  page: number
  pageSize: number
  totalPage: number
}

/** 后端分页响应使用 page_no / page_size / pages 字段。 */
type BackendWorkflowPage = {
  page_no: number
  page_size: number
  items: Workflow[]
  total: number
  pages: number
}

type BackendWorkflowRunPage = {
  page_no: number
  page_size: number
  items: WorkflowRun[]
  total: number
  pages: number
}

function toPage<T>(data: {
  page_no: number
  page_size: number
  items: T[]
  total: number
  pages: number
}) {
  return {
    items: data?.items ?? [],
    total: Number(data?.total ?? 0),
    page: Number(data?.page_no ?? 1),
    pageSize: Number(data?.page_size ?? 20),
    totalPage: Number(data?.pages ?? 1),
  }
}

export async function listWorkflows(
  platformId: number,
  params: { page?: number; pageSize?: number; status?: string } = {}
): Promise<WorkflowPage> {
  const { data } = await http.get<BackendWorkflowPage>(
    `/platforms/${platformId}/workflows`,
    {
      params: {
        page: params.page,
        page_size: params.pageSize,
        status: params.status,
      },
    }
  )
  return toPage<Workflow>(data)
}

export async function getWorkflow(
  platformId: number,
  workflowId: number
): Promise<Workflow> {
  const { data } = await http.get<Workflow>(
    `/platforms/${platformId}/workflows/${workflowId}`
  )
  return data
}

export async function createWorkflow(
  platformId: number,
  input: WorkflowCreate
): Promise<Workflow> {
  const { data } = await http.post<Workflow>(
    `/platforms/${platformId}/workflows`,
    input
  )
  return data
}

export async function updateWorkflow(
  platformId: number,
  workflowId: number,
  input: WorkflowUpdate
): Promise<Workflow> {
  const { data } = await http.patch<Workflow>(
    `/platforms/${platformId}/workflows/${workflowId}`,
    input
  )
  return data
}

/** 删除工作流；返回本次实际删除的行数。 */
export async function deleteWorkflow(
  platformId: number,
  workflowId: number
): Promise<{ deleted: number }> {
  const { data } = await http.delete<{ deleted: number }>(
    `/platforms/${platformId}/workflows/${workflowId}`
  )
  return data
}

/** 立即运行一次；后端只排队后立刻返回，实际执行结果要去运行记录里看。 */
export async function runWorkflowNow(
  platformId: number,
  workflowId: number
): Promise<{ run: WorkflowRun; message: string }> {
  const { data } = await http.post<{ run: WorkflowRun; message: string }>(
    `/platforms/${platformId}/workflows/${workflowId}/run`
  )
  return data
}

export async function listWorkflowRuns(
  platformId: number,
  workflowId: number,
  params: { page?: number; pageSize?: number; status?: string } = {}
): Promise<WorkflowRunPage> {
  const { data } = await http.get<BackendWorkflowRunPage>(
    `/platforms/${platformId}/workflows/${workflowId}/runs`,
    {
      params: {
        page: params.page,
        page_size: params.pageSize,
        status: params.status,
      },
    }
  )
  return toPage<WorkflowRun>(data)
}

/** 读取单次运行的每步明细（状态、兜底值、错误、模型可见输出）。 */
export async function getWorkflowRunDetail(
  platformId: number,
  workflowId: number,
  runId: number
): Promise<WorkflowRunDetail> {
  const { data } = await http.get<WorkflowRunDetail>(
    `/platforms/${platformId}/workflows/${workflowId}/runs/${runId}`
  )
  return data
}
