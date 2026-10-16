import { http } from '@/lib/http'

/**
 * 工作流步骤类型：agent 跑一轮 Agent 对话，tool 直接调用一个工具，
 * condition 只按上游输出做结构化判定（不调模型、不调工具、不产生会话）。
 */
export type WorkflowStepKind = 'agent' | 'tool' | 'condition'

/**
 * 同一拓扑层里互不依赖的步骤数上限，与后端 MAX_PARALLEL_BRANCHES 对齐。
 * 前端本地校验用同一个数字，避免用户提交后才收到 400。
 */
export const MAX_PARALLEL_BRANCHES = 8

/** 步骤失败策略：abort 中止整条工作流；continue_with_default 用兜底输出继续；fail_branch 走 @failed 出口继续，整条 run 仍以 completed 收尾。 */
export type WorkflowStepOnError =
  | 'abort'
  | 'continue_with_default'
  | 'fail_branch'

/**
 * 依赖条目里的出口限定分隔符：`"<step_id>@<handle>"` 表示「只在该上游走这条出口时到达」，
 * 不带后缀等价于 `"<step_id>@default"`。与后端 validators.HANDLE_SEPARATOR 对齐；
 * 出口决定运行期能否到达（到达触发），基础 step_id 才是依赖关系本身。
 */
export const BRANCH_HANDLE_SEPARATOR = '@'

/**
 * 比较类谓词算子：left 只能是一个 {{step_id.output}} 引用，right 仅 not_empty 可缺省
 * （matches 的 right 是正则表达式）。谓词刻意不做表达式字符串：结构化形状才能在保存期
 * 就把未知算子、非上游引用、非法正则全部拦下。
 */
export type ConditionComparisonOp =
  | 'equals'
  | 'contains'
  | 'not_empty'
  | 'matches'

/** 组合类谓词算子：all/any 的 children 为 1..16 个，not 恰好 1 个；嵌套深度上限 4。 */
export type ConditionLogicalOp = 'all' | 'any' | 'not'

export type ConditionOp = ConditionComparisonOp | ConditionLogicalOp

/** 比较类谓词：把某个上游步骤的输出与一个字面量做比较；不带 children。 */
export type ConditionComparisonPredicate = {
  op: ConditionComparisonOp
  /** 恰好一个 {{step_id.output}} 形式的模板引用 */
  left: string
  /** 比较值；op=not_empty 时不需要（后端也拒绝多余的值） */
  right?: string | null
}

/** 组合类谓词：把若干子谓词用 all / any / not 组合起来；不带 left / right。 */
export type ConditionLogicalPredicate = {
  op: ConditionLogicalOp
  children: ConditionPredicate[]
}

export type ConditionPredicate =
  | ConditionComparisonPredicate
  | ConditionLogicalPredicate

/**
 * 条件步骤的一个分支：判定按数组顺序取第一个为真的分支。
 * when 为空（null/undefined）即无条件兜底分支——它保证条件全不成立时这一步仍有路可走，
 * 因此必须恰好有一个且排在最后。
 */
export type ConditionBranch = {
  name: string
  when?: ConditionPredicate | null
}

/** 画布坐标；只影响画布布局，不参与执行语义。 */
export type WorkflowNodePosition = { x: number; y: number }

/** 工作流步骤：DAG 里的一个执行单元。kind=agent 跑一轮 Agent，kind=tool 直接调一个工具。 */
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
  /** 输入绑定：{参数名: [前序 step_id, 输出路径]}；路径目前只允许 "output"（该步模型可见输出） */
  input_bindings: Record<string, [string, string]>
  on_error: WorkflowStepOnError
  /** on_error=continue_with_default 时使用的兜底输出 */
  default_output: string | null
  timeout_seconds: number | null
  /** 失败后额外重试几次（0 表示不重试）；重试用同一份输入，用尽后 on_error 才生效 */
  max_retries: number
  /**
   * 本步依赖的步骤 id 列表。
   * null（缺省）语义 = 依赖序列中的前一个步骤，存量线性定义靠它保持零改动兼容；
   * 显式 [] = 起点（并行分支的第二条及以后必须写它）；显式数组 = 这些上游全部完成后才执行。
   */
  depends_on: string[] | null
  /**
   * 仅 kind=condition 时使用：本步声明的分支出口（分支名即出口名），
   * 恰好一个无条件兜底分支且必须排在最后；其它类型的步骤为 null。
   */
  branches: ConditionBranch[] | null
  /** 画布坐标；null 表示还没在画布上摆放，前端按拓扑层自动布局 */
  position: WorkflowNodePosition | null
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
}

/**
 * 写入用的步骤：step_id / name / kind / on_error 必填，其余字段可省略，
 * 也可以显式传 null 表示「用后端默认值」（后端这些字段都接受 null）。
 */
type WorkflowStepOptionalFields = Omit<
  WorkflowStep,
  'step_id' | 'name' | 'kind' | 'on_error'
>

export type WorkflowStepWrite = Pick<
  WorkflowStep,
  'step_id' | 'name' | 'kind' | 'on_error'
> & {
  [K in keyof WorkflowStepOptionalFields]?: WorkflowStepOptionalFields[K] | null
}

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
}

/** 步骤运行：某次运行里一步的执行记录。 */
export type WorkflowStepRun = {
  id: number
  run_id: number
  step_id: string
  seq: number
  node_type: WorkflowStepKind
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

/**
 * 后端把 steps 编译成 definition.nodes 存储（node 比 step 多一个 seq 序号，
 * 少一个 steps 数组层级），因此读取时要还原回表单直接可用的有序 steps。
 *
 * DAG 重构后每个 node 额外带 depends_on 与 position 两键（可为 null），
 * 这两个字段也必须带回前端，否则画布会丢掉已有的依赖关系与布局。
 */
type WorkflowNode = Omit<
  WorkflowStep,
  'max_retries' | 'depends_on' | 'position'
> & {
  seq?: number
  max_retries?: number | null
  depends_on?: string[] | null
  position?: WorkflowNodePosition | null
}

/** definition 编译结果；edges 由 depends_on 推导，读取时用来自检，不参与编辑。 */
export type WorkflowEdge = {
  edge_id: string
  source: string
  target: string
  source_handle: string
}

type WorkflowPayload = Omit<Workflow, 'steps'> & {
  steps?: WorkflowStep[]
  definition?: { nodes?: WorkflowNode[]; edges?: WorkflowEdge[] } | null
}

/** 把后端 node 的 position 收敛成合法坐标；脏数据不让它污染画布。 */
function nodeToPosition(value: unknown): WorkflowNodePosition | null {
  if (!value || typeof value !== 'object') return null
  const { x, y } = value as { x?: unknown; y?: unknown }
  if (typeof x !== 'number' || typeof y !== 'number') return null
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null
  return { x, y }
}

/**
 * 读侧收敛谓词形状：后端的 `model_dump()` 会把请求里省略的 `children` 补成 `null`，
 * 而编辑器用「有没有 children 这个键」判断它是不是组合算子 —— 留着 `children: null`
 * 会让渲染层把 null 当子条件列表用（`.map` 直接抛错）、也让保存校验误判成
 * 「比较算子带了子条件」。这里把「不是数组的 children」整键丢掉，并递归处理子条件。
 */
function toPredicate(value: unknown): ConditionPredicate | null {
  if (!value || typeof value !== 'object') return null
  const source = value as Record<string, unknown>
  const children = (value as { children?: unknown }).children
  const predicate: Record<string, unknown> = { ...source }
  if (Array.isArray(children)) {
    predicate.children = children.map((child) => toPredicate(child) ?? child)
  } else {
    delete predicate.children
  }
  return predicate as ConditionPredicate
}

/**
 * 把后端 node 的 branches 收敛成编辑器能直接用的形状：
 * 没有分支名或不是对象的条目直接丢弃，避免脏数据在分支编辑器里渲染成空白行。
 */
function nodeToBranches(value: unknown): ConditionBranch[] | null {
  if (!Array.isArray(value)) return null
  const branches = value
    .filter(
      (item): item is ConditionBranch =>
        !!item &&
        typeof item === 'object' &&
        typeof (item as ConditionBranch).name === 'string'
    )
    .map((branch) => ({
      name: branch.name,
      when: toPredicate(branch.when),
    }))
  return branches.length > 0 ? branches : null
}

function nodeToStep(node: WorkflowNode): WorkflowStep {
  const dependsOn = Array.isArray(node.depends_on)
    ? node.depends_on.filter((item): item is string => typeof item === 'string')
    : null
  return {
    step_id: node.step_id,
    name: node.name,
    kind: node.kind,
    agent_id: node.agent_id ?? null,
    prompt: node.prompt ?? null,
    tool_name: node.tool_name ?? null,
    tool_arguments: node.tool_arguments ?? null,
    input_bindings: node.input_bindings ?? {},
    on_error: node.on_error ?? 'abort',
    default_output: node.default_output ?? null,
    timeout_seconds: node.timeout_seconds ?? null,
    max_retries: node.max_retries ?? 0,
    depends_on: dependsOn,
    branches: nodeToBranches(node.branches),
    position: nodeToPosition(node.position),
  }
}

/** 把接口返回的工作流还原成带 steps 的形态；已经带 steps 的原样返回。 */
export function toWorkflow(payload: WorkflowPayload): Workflow {
  if (payload.steps) return { ...payload, steps: payload.steps }
  const nodes = [...(payload.definition?.nodes ?? [])]
  nodes.sort((left, right) => (left.seq ?? 0) - (right.seq ?? 0))
  return { ...payload, steps: nodes.map(nodeToStep) }
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
  const page = toPage<WorkflowPayload>(data)
  return { ...page, items: page.items.map(toWorkflow) }
}

export async function getWorkflow(
  platformId: number,
  workflowId: number
): Promise<Workflow> {
  const { data } = await http.get<WorkflowPayload>(
    `/platforms/${platformId}/workflows/${workflowId}`
  )
  return toWorkflow(data)
}

export async function createWorkflow(
  platformId: number,
  input: WorkflowCreate
): Promise<Workflow> {
  const { data } = await http.post<WorkflowPayload>(
    `/platforms/${platformId}/workflows`,
    input
  )
  return toWorkflow(data)
}

export async function updateWorkflow(
  platformId: number,
  workflowId: number,
  input: WorkflowUpdate
): Promise<Workflow> {
  const { data } = await http.patch<WorkflowPayload>(
    `/platforms/${platformId}/workflows/${workflowId}`,
    input
  )
  return toWorkflow(data)
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
