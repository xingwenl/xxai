import { http } from '@/lib/http'

/** 任务：一条按时间触发、到点自动跑一轮 Agent 对话的配置。 */
export type Task = {
  id: number
  platform_id: number
  agent_id: number
  /** 为空表示平台级任务（仅平台管理员可管理） */
  owner_user_id: number | null
  name: string
  prompt: string
  model_id: number | null
  trigger_type: 'cron' | 'once'
  cron_expression: string | null
  run_at: string | null
  timezone: string
  status: 'active' | 'paused'
  next_run_at: string | null
  last_run_at: string | null
  created_by_type: 'user' | 'agent' | 'integration'
  created_by_user_id: number | null
  created_by_agent_id: number | null
  run_as_type: string
  run_as_user_id: number | null
  auto_approve: boolean
  strict_approval: boolean
  timeout_seconds: number
  created_at: string
  updated_at: string
}

/** 任务运行：任务的一次执行记录（含被跳过的触发点）。 */
export type TaskRun = {
  id: number
  task_id: number
  status: 'running' | 'completed' | 'failed' | 'skipped'
  trigger_kind: 'scheduled' | 'manual'
  planned_at: string | null
  started_at: string | null
  finished_at: string | null
  conversation_id: number | null
  agent_loop_run_id: number | null
  error_message: string | null
  skip_reason: string | null
  auto_approved_count: number
  created_at: string
  updated_at: string
}

export type TaskPage = {
  items: Task[]
  total: number
  page: number
  pageSize: number
  totalPage: number
}

export type TaskRunPage = {
  items: TaskRun[]
  total: number
  page: number
  pageSize: number
  totalPage: number
}

export type TaskInput = {
  name: string
  prompt: string
  agent_id: number
  trigger_type: 'cron' | 'once'
  cron_expression?: string | null
  run_at?: string | null
  timezone: string
  model_id?: number | null
  auto_approve: boolean
  strict_approval: boolean
  timeout_seconds: number
}

export type TaskUpdateInput = Partial<TaskInput> & {
  status?: 'active' | 'paused'
}

/** 后端分页响应使用 page_no / page_size / pages 字段。 */
type BackendTaskPage = {
  page_no: number
  page_size: number
  items: Task[]
  total: number
  pages: number
}

type BackendTaskRunPage = {
  page_no: number
  page_size: number
  items: TaskRun[]
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

export async function listTasks(
  platformId: number,
  params: { page?: number; pageSize?: number; status?: string } = {}
): Promise<TaskPage> {
  const { data } = await http.get<BackendTaskPage>(
    `/platforms/${platformId}/tasks`,
    {
      params: {
        page: params.page,
        page_size: params.pageSize,
        status: params.status,
      },
    }
  )
  return toPage<Task>(data)
}

export async function getTask(
  platformId: number,
  taskId: number
): Promise<Task> {
  const { data } = await http.get<Task>(
    `/platforms/${platformId}/tasks/${taskId}`
  )
  return data
}

export async function createTask(
  platformId: number,
  input: TaskInput
): Promise<Task> {
  const { data } = await http.post<Task>(
    `/platforms/${platformId}/tasks`,
    input
  )
  return data
}

export async function updateTask(
  platformId: number,
  taskId: number,
  input: TaskUpdateInput
): Promise<Task> {
  const { data } = await http.patch<Task>(
    `/platforms/${platformId}/tasks/${taskId}`,
    input
  )
  return data
}

export async function deleteTask(
  platformId: number,
  taskId: number
): Promise<void> {
  await http.delete(`/platforms/${platformId}/tasks/${taskId}`)
}

/** 立即运行一次；返回新建的执行记录（若任务在运行中则为 skipped 记录）。 */
export async function runTaskNow(
  platformId: number,
  taskId: number
): Promise<{ run: TaskRun; message: string }> {
  const { data } = await http.post<{ run: TaskRun; message: string }>(
    `/platforms/${platformId}/tasks/${taskId}/run`
  )
  return data
}

export async function listTaskRuns(
  platformId: number,
  taskId: number,
  params: { page?: number; pageSize?: number; status?: string } = {}
): Promise<TaskRunPage> {
  const { data } = await http.get<BackendTaskRunPage>(
    `/platforms/${platformId}/tasks/${taskId}/runs`,
    {
      params: {
        page: params.page,
        page_size: params.pageSize,
        status: params.status,
      },
    }
  )
  return toPage<TaskRun>(data)
}

/**
 * 父运行派生的子运行摘要（运行期动态委派）。
 *
 * 只读：子运行有独立会话与运行记录，这里只带渲染所需的终态信息，
 * 契约字段名与 ai-sdk 的 `DelegatedRun` 一致（camelCase）。
 */
export type TaskRunDelegatedRun = {
  /** 子运行 ID（后端 `agent_loop_runs.id` 字符串化）。 */
  id: string
  agentSlug: string
  agentName: string
  status: string
  summary: string | null
  conversationId: string | null
}

/** 执行过程中的一步。 */
export type TaskRunStep = {
  id: string
  sequence: number
  step_type: string
  title: string | null
  status: string | null
  output_summary: string | null
  thinking_text: string | null
  tool_name: string | null
  skill_name: string | null
  /** 本步骤（一次委派工具调用）扇出的子运行 ID；无子运行时为 null。 */
  delegatedRunIds?: string[] | null
  error: string | null
}

/** 单次运行的执行过程详情。 */
export type TaskRunDetail = {
  run: TaskRun
  loop_id: string | null
  loop_status: string | null
  loop_summary: string | null
  /** 本次运行派生的子运行摘要；无子运行时为 null。 */
  delegatedRuns?: TaskRunDelegatedRun[] | null
  steps: TaskRunStep[]
}

/** 读取单次运行的执行过程（每步的思考、工具调用与结果）。 */
export async function getTaskRunDetail(
  platformId: number,
  taskId: number,
  runId: number
): Promise<TaskRunDetail> {
  const { data } = await http.get<TaskRunDetail>(
    `/platforms/${platformId}/tasks/${taskId}/runs/${runId}/detail`
  )
  return data
}
