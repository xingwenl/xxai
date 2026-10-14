import { useMemo, useState } from 'react'
import {
  MAX_PARALLEL_BRANCHES,
  type Workflow,
  type WorkflowNodePosition,
  type WorkflowStepKind,
  type WorkflowStepOnError,
  type WorkflowStepWrite,
  type WorkflowUpdate,
} from '@/api/workflow'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
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
import { WorkflowCanvas } from '@/features/workflows/workflow-canvas'
import {
  positionPatchesFromChanges,
  useCanvasEdges,
  useCanvasNodes,
} from '@/features/workflows/workflow-canvas-model'
import {
  collectTemplateReferences,
  extractMentions,
  resolveDependencies,
  toDependsOnWrite,
  validateDag,
  type DagIssue,
} from '@/features/workflows/workflow-dag'

/** 下拉框不允许空字符串值，用哨兵值表示「不覆盖 / 未选择」。 */
const NO_AGENT_OVERRIDE = '__default__'
const NO_PREVIOUS_STEP = '__none__'

/** 目前唯一可引用的输出路径；后端保存时也只接受这一个值。 */
const OUTPUT_PATH = 'output'

/** 每步失败后的额外重试次数；上限与后端 validators.MAX_STEP_RETRIES 对齐。 */
const MAX_RETRIES_OPTIONS = [0, 1, 2, 3, 4, 5]

const ON_ERROR_OPTIONS: { value: WorkflowStepOnError; label: string }[] = [
  { value: 'abort', label: '中止整条工作流（abort）' },
  {
    value: 'continue_with_default',
    label: '使用兜底输出继续（continue_with_default）',
  },
  // fail_branch 依赖边上的失败出口，v1 没有分支，故保留枚举值并明确标注暂不可用。
  { value: 'fail_branch', label: '失败分支（fail_branch，暂未实现）' },
]

/**
 * 步骤草稿：接口里的 tool_arguments 是对象、input_bindings 是 record，
 * 两者都不适合直接绑到表单控件上，这里在编辑态改成文本与行式结构，提交时再转回接口类型。
 */
type StepDraft = {
  step_id: string
  name: string
  kind: WorkflowStepKind
  agent_id: number | null
  prompt: string
  tool_name: string
  tool_arguments_text: string
  bindings: { key: string; step_id: string; path: string }[]
  on_error: WorkflowStepOnError
  default_output: string
  /** 空字符串表示「用工作流级超时」 */
  timeout_seconds: string
  /** 失败后额外重试次数（0–5）；用下拉而不是输入框，避免出现后端不接受的取值 */
  max_retries: number
  /**
   * 已折算成显式数组的上游依赖；null 的缺省语义在 toDraft 时已按序列前驱展开，
   * 这样画布与校验都只需要处理一种形态。
   */
  depends_on: string[]
  /** 画布坐标；null 表示还没在画布上摆放，渲染时按拓扑层自动布局 */
  position: WorkflowNodePosition | null
}

type DefinitionDraft = {
  name: string
  description: string
  agent_id: number
  max_steps: number
  timeout_seconds: number
  auto_approve: boolean
  strict_approval: boolean
  steps: StepDraft[]
}

function toStepDraft(step: WorkflowStepWrite, dependsOn: string[]): StepDraft {
  return {
    step_id: step.step_id,
    name: step.name,
    kind: step.kind,
    agent_id: step.agent_id ?? null,
    prompt: step.prompt ?? '',
    tool_name: step.tool_name ?? '',
    tool_arguments_text: step.tool_arguments
      ? JSON.stringify(step.tool_arguments, null, 2)
      : '',
    bindings: Object.entries(step.input_bindings ?? {}).map(([key, value]) => ({
      key,
      step_id: value?.[0] ?? '',
      path: value?.[1] ?? '',
    })),
    on_error: step.on_error,
    default_output: step.default_output ?? '',
    timeout_seconds:
      step.timeout_seconds == null ? '' : String(step.timeout_seconds),
    max_retries: step.max_retries ?? 0,
    depends_on: dependsOn,
    position: step.position ?? null,
  }
}

function toDraft(workflow: Workflow): DefinitionDraft {
  // null 语义 = 依赖前一个步骤；在这里一次性展开，后续所有结构计算都用显式数组。
  const resolved = resolveDependencies(workflow.steps)
  return {
    name: workflow.name,
    description: workflow.description ?? '',
    agent_id: workflow.agent_id,
    max_steps: workflow.max_steps,
    timeout_seconds: workflow.timeout_seconds,
    auto_approve: workflow.auto_approve,
    strict_approval: workflow.strict_approval,
    steps: workflow.steps.map((step, index) =>
      toStepDraft(step, resolved[index])
    ),
  }
}

/**
 * 新步骤默认依赖「当前最后一步」，保持线性追加直觉；
 * 需要并行分支时用户自己在画布上删掉这根线（或从别的节点拉线）。
 */
function newStepDraft(seq: number, dependsOn: string[]): StepDraft {
  return {
    step_id: `step_${seq}`,
    name: `步骤 ${seq}`,
    kind: 'agent',
    agent_id: null,
    prompt: '',
    tool_name: '',
    tool_arguments_text: '',
    bindings: [],
    on_error: 'abort',
    default_output: '',
    timeout_seconds: '',
    max_retries: 0,
    depends_on: dependsOn,
    position: null,
  }
}

/** 参数模板必须是 JSON 对象；空文本表示「无参数」。 */
function parseToolArguments(text: string): Record<string, unknown> | null {
  const trimmed = text.trim()
  if (!trimmed) return null
  const parsed: unknown = JSON.parse(trimmed)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('参数模板必须是 JSON 对象')
  }
  return parsed as Record<string, unknown>
}

/**
 * 保存前的逐步骤字段校验，口径与后端一致：
 * step_id 非空且唯一、绑定声明完整、超时与重试次数在合法区间。
 *
 * 结构性问题（成环 / 悬空依赖 / 引用非上游 / 并行宽度）交给 validateDag，
 * 这里只管单步字段本身，避免两处规则各说各话。
 */
function validateStepFields(draft: DefinitionDraft): DagIssue[] {
  const issues: DagIssue[] = []
  if (!draft.name.trim())
    issues.push({ message: '请填写工作流名称', stepId: null })
  if (!draft.agent_id)
    issues.push({ message: '请选择默认智能体', stepId: null })
  if (draft.steps.length === 0)
    issues.push({ message: '至少需要一个步骤', stepId: null })
  if (draft.steps.length > draft.max_steps) {
    issues.push({
      message: `步骤数 ${draft.steps.length} 超过上限 ${draft.max_steps}`,
      stepId: null,
    })
  }
  if (draft.timeout_seconds < 30 || draft.timeout_seconds > 7200) {
    issues.push({
      message: '整条超时必须落在 30 到 7200 秒之间',
      stepId: null,
    })
  }

  const seen = new Set<string>()
  draft.steps.forEach((step, index) => {
    const label = `第 ${index + 1} 步`
    const stepId = step.step_id.trim()
    if (!stepId) {
      issues.push({ message: `${label}缺少步骤 ID`, stepId: null })
    } else if (seen.has(stepId)) {
      issues.push({ message: `${label}的步骤 ID「${stepId}」重复`, stepId })
    } else if (!/^[A-Za-z0-9_-]+$/.test(stepId)) {
      issues.push({
        message: `${label}的步骤 ID 只能包含字母、数字、下划线和连字符`,
        stepId,
      })
    } else if (stepId.length > 64) {
      issues.push({ message: `${label}的步骤 ID 不能超过 64 个字符`, stepId })
    }
    seen.add(stepId)

    if (!step.name.trim()) issues.push({ message: `${label}缺少名称`, stepId })
    else if (step.name.trim().length > 200) {
      issues.push({ message: `${label}的名称不能超过 200 个字符`, stepId })
    }
    if (step.kind === 'agent' && !step.prompt.trim()) {
      issues.push({
        message: `${label}是 Agent 步骤，必须填写指令`,
        stepId,
      })
    }
    if (step.kind === 'tool' && !step.tool_name.trim()) {
      issues.push({
        message: `${label}是工具步骤，必须填写工具名`,
        stepId,
      })
    }
    try {
      parseToolArguments(step.tool_arguments_text)
    } catch (error) {
      issues.push({
        message: `${label}的参数模板不是合法 JSON 对象：${String(error)}`,
        stepId,
      })
    }
    if (step.timeout_seconds.trim()) {
      const seconds = Number(step.timeout_seconds)
      // 后端单步超时区间是 30..7200 秒，前端先按同一区间拦下，避免提交后才 422。
      if (!Number.isFinite(seconds) || seconds < 30 || seconds > 7200) {
        issues.push({
          message: `${label}的步骤超时必须是 30 到 7200 之间的秒数`,
          stepId,
        })
      }
    }
    // 声明「失败也继续」就必须给兜底值，否则运行期只能用空串污染下游。
    if (
      step.on_error === 'continue_with_default' &&
      !step.default_output.trim()
    ) {
      issues.push({
        message: `${label}选择「失败后使用兜底输出」时必须填写兜底输出`,
        stepId,
      })
    }
    if (
      !Number.isInteger(step.max_retries) ||
      step.max_retries < 0 ||
      step.max_retries > MAX_RETRIES_OPTIONS.length - 1
    ) {
      issues.push({
        message: `${label}的重试次数必须是 0 到 ${MAX_RETRIES_OPTIONS.length - 1} 之间的整数`,
        stepId,
      })
    }

    // 绑定行只做了「参数名 + 目标步骤」的半成品声明时，先在这里拦下；
    // 目标步骤是否真的存在、是否在上游，由 validateDag 统一裁定。
    Object.entries(groupBindings(step)).forEach(([key, binding]) => {
      if (!binding[0]) {
        issues.push({
          message: `${label}的参数「${key}」还没选择引用的步骤`,
          stepId,
        })
      }
      if (!binding[1]) {
        issues.push({
          message: `${label}的参数「${key}」缺少输出路径`,
          stepId,
        })
      }
    })
  })

  return issues
}

/**
 * 汇总一步声明的所有外部引用：
 * input_bindings 的 value_selector 与提示词 / 参数模板里的 {{step_id.output}}。
 */
function referencesOfStep(
  step: StepDraft
): { key: string; stepId: string; path: string }[] {
  const references: { key: string; stepId: string; path: string }[] = []
  const seen = new Set<string>()
  const push = (key: string, stepId: string, path: string) => {
    const dedupe = `${key}|${stepId}|${path}`
    if (seen.has(dedupe)) return
    seen.add(dedupe)
    references.push({ key, stepId, path })
  }

  Object.entries(groupBindings(step)).forEach(([key, binding]) => {
    // 空目标已在字段校验里报过，这里跳过以免报出重复噪音。
    if (!binding[0]) return
    push(key, binding[0], binding[1])
  })

  const prompt = step.kind === 'agent' ? step.prompt : null
  let toolArguments: unknown = null
  if (step.kind === 'tool') {
    try {
      toolArguments = parseToolArguments(step.tool_arguments_text)
    } catch {
      // 模板不是合法 JSON 时已经报过错，这里不再重复解析。
      toolArguments = null
    }
  }
  collectTemplateReferences(prompt, toolArguments).forEach((reference) => {
    push('', reference.stepId, reference.path)
  })
  // 参数模板里的引用可能存在于模板字符串任意位置，collectTemplateReferences
  // 已经覆盖嵌套结构；这里再兜一层，防止模板 JSON 解析失败时漏掉提示词里的引用。
  if (step.kind === 'agent') {
    extractMentions(step.prompt).forEach((raw) => {
      const dot = raw.indexOf('.')
      if (dot <= 0) return
      push('', raw.slice(0, dot), raw.slice(dot + 1))
    })
  }

  return references
}

/** 依据校验结果统计每个步骤命中的问题数，用于画布节点飘红。 */
function countIssuesByStep(issues: DagIssue[], stepIds: string[]) {
  const counts = new Map<string, number>()
  stepIds.forEach((stepId) => counts.set(stepId, 0))
  issues.forEach((issue) => {
    if (!issue.stepId) return
    counts.set(issue.stepId, (counts.get(issue.stepId) ?? 0) + 1)
  })
  return counts
}

/** 行式绑定合并成接口要的 record，顺带丢掉没填参数名的空行。 */
function groupBindings(step: StepDraft): Record<string, [string, string]> {
  const bindings: Record<string, [string, string]> = {}
  step.bindings.forEach((binding) => {
    const key = binding.key.trim()
    if (key) bindings[key] = [binding.step_id.trim(), binding.path.trim()]
  })
  return bindings
}

function toStepWrite(
  step: StepDraft,
  resolved: string[][],
  stepIds: string[],
  index: number
): WorkflowStepWrite {
  return {
    step_id: step.step_id.trim(),
    name: step.name.trim(),
    kind: step.kind,
    agent_id: step.kind === 'agent' ? step.agent_id : null,
    prompt: step.kind === 'agent' ? step.prompt.trim() || null : null,
    tool_name: step.kind === 'tool' ? step.tool_name.trim() || null : null,
    // 这两个字段后端是非空字典，显式传 null 会被 422 拒绝；
    // 参数为空时提交 {}，语义与后端「空参数」一致。
    tool_arguments:
      step.kind === 'tool'
        ? (parseToolArguments(step.tool_arguments_text) ?? {})
        : {},
    input_bindings: groupBindings(step),
    on_error: step.on_error,
    default_output:
      step.on_error === 'continue_with_default'
        ? step.default_output.trim() || null
        : null,
    timeout_seconds: step.timeout_seconds.trim()
      ? Number(step.timeout_seconds)
      : null,
    max_retries: step.max_retries > 0 ? step.max_retries : null,
    // 与缺省语义等价的线性单依赖仍写成 null，存量定义保存后形状不变。
    depends_on: toDependsOnWrite(resolved, stepIds, index),
    position: step.position,
  }
}

/**
 * 工作流定义编辑器：基本信息 + 「DAG 画布 + 属性面板」。
 *
 * 画布负责结构（依赖关系与摆放位置），右侧属性面板负责字段，
 * 保存时整份 steps 一起提交（PATCH），后端按新定义把 version 加一。
 */
export function WorkflowDefinitionForm({
  workflow,
  agents,
  isSaving,
  onSubmit,
}: {
  workflow: Workflow
  agents: { id: number; name: string }[]
  isSaving: boolean
  onSubmit: (input: WorkflowUpdate) => void
}) {
  const [draft, setDraft] = useState<DefinitionDraft>(() => toDraft(workflow))
  const [issues, setIssues] = useState<DagIssue[]>([])
  const [selectedStepId, setSelectedStepId] = useState<string | null>(
    () => workflow.steps[0]?.step_id ?? null
  )

  // 结构相关的派生值统一在 useMemo 里算：画布节点 / 边依赖这些数组的引用稳定性，
  // 每次输入都新建数组会让画布整块重渲染。
  const resolved = useMemo(
    () => resolveDependencies(draft.steps),
    [draft.steps]
  )
  const stepIds = useMemo(
    () => draft.steps.map((step) => step.step_id.trim()),
    [draft.steps]
  )
  const stepIdSet = useMemo(() => new Set(stepIds), [stepIds])
  const referencesByStep = useMemo(
    () => draft.steps.map((step) => referencesOfStep(step)),
    [draft.steps]
  )
  const errorCountByStep = useMemo(
    () => countIssuesByStep(issues, stepIds),
    [issues, stepIds]
  )
  /**
   * 每个步骤的祖先集合（直接或间接依赖）。
   * 属性面板的「引用步骤」下拉只列祖先，让用户根本选不到会被后端拒绝的目标。
   */
  const ancestorsByStep = useMemo(() => {
    const parents = new Map<string, string[]>()
    stepIds.forEach((stepId) => parents.set(stepId, []))
    resolved.forEach((deps, index) => {
      deps.forEach((dep) => parents.get(stepIds[index])?.push(dep))
    })
    const result = new Map<string, Set<string>>()
    stepIds.forEach((stepId) => {
      const seen = new Set<string>()
      const stack = [...(parents.get(stepId) ?? [])]
      while (stack.length > 0) {
        const current = stack.pop()!
        if (seen.has(current)) continue
        seen.add(current)
        stack.push(...(parents.get(current) ?? []))
      }
      result.set(stepId, seen)
    })
    return result
  }, [stepIds, resolved])
  const canvasNodes = useCanvasNodes(draft.steps, resolved, errorCountByStep)
  const canvasEdges = useCanvasEdges(resolved, stepIds)

  const selectedIndex = selectedStepId
    ? draft.steps.findIndex((step) => step.step_id === selectedStepId)
    : -1
  const selectedStep = selectedIndex >= 0 ? draft.steps[selectedIndex] : null

  function updateStep(index: number, patch: Partial<StepDraft>) {
    setDraft((prev) => ({
      ...prev,
      steps: prev.steps.map((step, i) =>
        i === index ? { ...step, ...patch } : step
      ),
    }))
  }

  /** 把某个步骤 id 从其它步骤的依赖与输入绑定里摘干净，避免留下悬空引用。 */
  function detachReferences(
    steps: StepDraft[],
    removedId: string
  ): StepDraft[] {
    if (!removedId) return steps
    return steps.map((step) => ({
      ...step,
      depends_on: step.depends_on.filter((dep) => dep !== removedId),
      bindings: step.bindings.filter(
        (binding) => binding.step_id.trim() !== removedId
      ),
    }))
  }

  /** 删除步骤：同步清理其它步骤对它的依赖与引用，保持 DAG 自洽。 */
  function removeStep(index: number) {
    setDraft((prev) => {
      const removed = prev.steps[index]
      const steps = prev.steps.filter((_, i) => i !== index)
      return {
        ...prev,
        steps: detachReferences(steps, removed?.step_id.trim() ?? ''),
      }
    })
    setSelectedStepId((prevId) =>
      prevId === draft.steps[index]?.step_id ? null : prevId
    )
  }

  function addStep() {
    // 新步骤默认接在最后一个步骤之后，保持「线性追加」的直觉；
    // 需要并行分支时用户在画布上删掉这根线或改从别的节点拉线。
    const lastStepId = draft.steps[draft.steps.length - 1]?.step_id.trim() ?? ''
    let seq = draft.steps.length + 1
    while (draft.steps.some((step) => step.step_id === `step_${seq}`)) seq += 1
    const next = newStepDraft(seq, lastStepId ? [lastStepId] : [])
    setDraft((prev) => ({ ...prev, steps: [...prev.steps, next] }))
    setSelectedStepId(next.step_id)
  }

  /** 在画布上从 source 拉到 target：target 依赖 source（入边即依赖）。 */
  function connectSteps(source: string, target: string) {
    const targetIndex = draft.steps.findIndex(
      (step) => step.step_id.trim() === target
    )
    if (targetIndex < 0) return
    const step = draft.steps[targetIndex]
    if (step.depends_on.includes(source)) return
    updateStep(targetIndex, { depends_on: [...step.depends_on, source] })
  }

  function removeDependency(stepIndex: number, dep: string) {
    const step = draft.steps[stepIndex]
    updateStep(stepIndex, {
      depends_on: step.depends_on.filter((item) => item !== dep),
    })
  }

  function removeEdges(edges: { id: string }[]) {
    edges.forEach((edge) => {
      // edge.id 由 edgeId(source, target) 生成，形如 "a->b"；拆不出就跳过。
      const separator = '->'
      const at = edge.id.indexOf(separator)
      if (at <= 0) return
      const from = edge.id.slice(0, at)
      const to = edge.id.slice(at + separator.length)
      const targetIndex = draft.steps.findIndex(
        (step) => step.step_id.trim() === to
      )
      if (targetIndex < 0) return
      removeDependency(targetIndex, from)
    })
  }

  function updateBinding(
    index: number,
    bindingIndex: number,
    patch: Partial<StepDraft['bindings'][number]>
  ) {
    setDraft((prev) => ({
      ...prev,
      steps: prev.steps.map((step, i) =>
        i === index
          ? {
              ...step,
              bindings: step.bindings.map((binding, bi) =>
                bi === bindingIndex ? { ...binding, ...patch } : binding
              ),
            }
          : step
      ),
    }))
  }

  function addBinding(index: number) {
    // 未选中步骤时把引用默认指向上游第一步，减少一次下拉选择。
    const firstUpstream = resolved[index]?.[0] ?? ''
    setDraft((prev) => ({
      ...prev,
      steps: prev.steps.map((step, i) =>
        i === index
          ? {
              ...step,
              bindings: [
                ...step.bindings,
                // 路径预填唯一合法值，省得用户对着「输出路径」想填什么。
                { key: '', step_id: firstUpstream, path: OUTPUT_PATH },
              ],
            }
          : step
      ),
    }))
  }

  function removeBinding(index: number, bindingIndex: number) {
    setDraft((prev) => ({
      ...prev,
      steps: prev.steps.map((step, i) =>
        i === index
          ? {
              ...step,
              bindings: step.bindings.filter((_, bi) => bi !== bindingIndex),
            }
          : step
      ),
    }))
  }

  function handleSubmit() {
    // 单步字段校验与 DAG 结构校验分开：前者定位到输入框，后者定位到节点。
    const nextIssues = [
      ...validateStepFields(draft),
      ...validateDag(
        draft.steps,
        (_step, index) => referencesByStep[index] ?? []
      ),
    ]
    setIssues(nextIssues)
    if (nextIssues.length > 0) {
      setSelectedStepId(
        nextIssues.find((issue) => issue.stepId)?.stepId ?? selectedStepId
      )
      return
    }
    onSubmit({
      name: draft.name.trim(),
      description: draft.description.trim() || null,
      agent_id: draft.agent_id,
      max_steps: draft.max_steps,
      steps: draft.steps.map((step, index) =>
        toStepWrite(step, resolved, stepIds, index)
      ),
      timeout_seconds: draft.timeout_seconds,
      auto_approve: draft.auto_approve,
      strict_approval: draft.strict_approval,
    })
  }

  const selectedUpstreams = selectedStep?.depends_on ?? []
  const addableDependencies = selectedStep
    ? draft.steps.filter(
        (step) =>
          step.step_id.trim() !== selectedStep.step_id.trim() &&
          !selectedUpstreams.includes(step.step_id.trim()) &&
          stepIdSet.has(step.step_id.trim())
      )
    : []
  const referenceOptions = selectedStep
    ? draft.steps.filter((step) =>
        (ancestorsByStep.get(selectedStep.step_id.trim()) ?? new Set()).has(
          step.step_id.trim()
        )
      )
    : []

  return (
    <div className='flex flex-col gap-4'>
      <div className='grid gap-3 sm:grid-cols-2'>
        <Field label='名称'>
          <Input
            value={draft.name}
            onChange={(event) =>
              setDraft((prev) => ({ ...prev, name: event.target.value }))
            }
            placeholder='每日巡检'
          />
        </Field>

        <Field label='默认智能体' hint='步骤未覆盖 Agent 时用它执行'>
          <Select
            value={draft.agent_id ? String(draft.agent_id) : ''}
            onValueChange={(value) =>
              setDraft((prev) => ({ ...prev, agent_id: Number(value) }))
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
        </Field>

        <Field label='说明' className='sm:col-span-2'>
          <Textarea
            rows={2}
            value={draft.description}
            onChange={(event) =>
              setDraft((prev) => ({ ...prev, description: event.target.value }))
            }
            placeholder='这条工作流的用途，便于后台识别'
          />
        </Field>

        <Field label='步骤数上限'>
          <Input
            type='number'
            value={draft.max_steps}
            onChange={(event) =>
              setDraft((prev) => ({
                ...prev,
                max_steps: Number(event.target.value),
              }))
            }
          />
        </Field>

        <Field label='整条超时（秒）'>
          <Input
            type='number'
            value={draft.timeout_seconds}
            onChange={(event) =>
              setDraft((prev) => ({
                ...prev,
                timeout_seconds: Number(event.target.value),
              }))
            }
          />
        </Field>

        <div className='flex items-center justify-between rounded-md border p-3'>
          <div>
            <Label>自动批准工具</Label>
            <p className='text-xs text-muted-foreground'>
              无人值守时自动批准需要确认的工具调用
            </p>
          </div>
          <Switch
            checked={draft.auto_approve}
            onCheckedChange={(value) =>
              setDraft((prev) => ({ ...prev, auto_approve: value }))
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
            checked={draft.strict_approval}
            onCheckedChange={(value) =>
              setDraft((prev) => ({ ...prev, strict_approval: value }))
            }
          />
        </div>
      </div>

      <div className='flex flex-col gap-3 rounded-md border p-3 lg:flex-row'>
        <div className='flex min-w-0 flex-1 flex-col'>
          <div className='mb-2'>
            <h2 className='text-lg font-semibold'>步骤（DAG 画布）</h2>
            <p className='text-sm text-muted-foreground'>
              连线表示「先跑上游再跑下游」，汇聚节点等所有上游完成；引用只能指向上游步骤，
              同一层最多并行 {MAX_PARALLEL_BRANCHES} 个步骤。
            </p>
          </div>
          <WorkflowCanvas
            nodes={canvasNodes}
            edges={canvasEdges}
            selectedStepId={selectedStepId}
            onSelect={setSelectedStepId}
            onNodesChange={(changes) => {
              // 拖拽只回写坐标，重算边集的工作留给 depends_on。
              const patches = positionPatchesFromChanges(changes)
              if (patches.length === 0) return
              setDraft((prev) => ({
                ...prev,
                steps: prev.steps.map((step) => {
                  const patch = patches.find(
                    (item) => item.stepId === step.step_id.trim()
                  )
                  return patch ? { ...step, position: patch.position } : step
                }),
              }))
            }}
            onConnect={connectSteps}
            onEdgesDelete={removeEdges}
            onAddStep={addStep}
            onDeleteStep={(stepId) => {
              const index = draft.steps.findIndex(
                (step) => step.step_id.trim() === stepId
              )
              if (index >= 0) removeStep(index)
            }}
          />
        </div>

        <div className='w-full shrink-0 lg:w-[380px]'>
          <StepPropertyPanel
            step={selectedStep}
            index={selectedIndex}
            agents={agents}
            upstreamOptions={addableDependencies}
            referenceOptions={referenceOptions}
            upstreamSteps={draft.steps.filter((step) =>
              selectedUpstreams.includes(step.step_id.trim())
            )}
            issues={issues.filter(
              (issue) =>
                issue.stepId === null ||
                issue.stepId === (selectedStep?.step_id.trim() ?? '')
            )}
            onChange={(patch) => {
              if (selectedIndex >= 0) updateStep(selectedIndex, patch)
            }}
            onAddDependency={(stepId) => {
              if (selectedIndex >= 0) {
                updateStep(selectedIndex, {
                  depends_on: [...selectedUpstreams, stepId],
                })
              }
            }}
            onRemoveDependency={(stepId) => {
              if (selectedIndex >= 0) removeDependency(selectedIndex, stepId)
            }}
            onAddBinding={() => {
              if (selectedIndex >= 0) addBinding(selectedIndex)
            }}
            onUpdateBinding={(bindingIndex, patch) => {
              if (selectedIndex >= 0) {
                updateBinding(selectedIndex, bindingIndex, patch)
              }
            }}
            onRemoveBinding={(bindingIndex) => {
              if (selectedIndex >= 0) removeBinding(selectedIndex, bindingIndex)
            }}
          />
        </div>
      </div>

      {issues.length > 0 && (
        <ul className='flex flex-col gap-1 rounded-md border border-destructive/50 p-3 text-xs text-destructive'>
          {issues.map((issue) => (
            <li key={`${issue.stepId ?? ''}-${issue.message}`}>
              <button
                type='button'
                className='text-left hover:underline'
                onClick={() => issue.stepId && setSelectedStepId(issue.stepId)}
              >
                {issue.message}
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className='flex items-center gap-3'>
        <Button onClick={handleSubmit} disabled={isSaving}>
          {isSaving ? '保存中...' : '保存定义'}
        </Button>
        <span className='text-xs text-muted-foreground'>
          保存会整份提交步骤并让版本号 +1；正在运行的记录仍按当时那一版解释。
        </span>
      </div>
    </div>
  )
}

/**
 * 右侧属性面板：编辑当前选中步骤的全部字段。
 *
 * 面板同时承担「某一步到底依赖谁」的展示，画布上的连线只表达先后，
 * 精确的增删在这里做，键盘/触屏用户也能完成操作。
 */
function StepPropertyPanel({
  step,
  index,
  agents,
  upstreamOptions,
  referenceOptions,
  upstreamSteps,
  issues,
  onChange,
  onAddDependency,
  onRemoveDependency,
  onAddBinding,
  onUpdateBinding,
  onRemoveBinding,
}: {
  step: StepDraft | null
  index: number
  agents: { id: number; name: string }[]
  upstreamOptions: StepDraft[]
  referenceOptions: StepDraft[]
  upstreamSteps: StepDraft[]
  issues: DagIssue[]
  onChange: (patch: Partial<StepDraft>) => void
  onAddDependency: (stepId: string) => void
  onRemoveDependency: (stepId: string) => void
  onAddBinding: () => void
  onUpdateBinding: (
    bindingIndex: number,
    patch: Partial<StepDraft['bindings'][number]>
  ) => void
  onRemoveBinding: (bindingIndex: number) => void
}) {
  if (!step) {
    return (
      <div className='rounded-md border p-4 text-sm text-muted-foreground'>
        在左侧画布上选中一个节点即可编辑它的字段；也可以点「新增步骤」创建。
      </div>
    )
  }

  // 覆盖的 Agent 可能已被删除或不在当前列表里，补一个只读选项避免下拉框显示空白。
  const agentOptions = [...agents]
  if (
    step.agent_id != null &&
    !agentOptions.some((a) => a.id === step.agent_id)
  ) {
    agentOptions.push({ id: step.agent_id, name: `#${step.agent_id}` })
  }
  const referenceCandidates = referenceOptions

  return (
    <div className='flex flex-col gap-3 rounded-md border p-3'>
      <div className='flex flex-wrap items-center gap-2'>
        <span className='text-sm font-medium'>第 {index + 1} 步</span>
        <Badge variant='outline'>
          {step.kind === 'agent' ? 'Agent 步骤' : '工具步骤'}
        </Badge>
        <span className='text-xs text-muted-foreground'>{step.step_id}</span>
      </div>

      {issues.length > 0 && (
        <ul className='flex flex-col gap-1 rounded-md border border-destructive/50 p-2 text-xs text-destructive'>
          {issues.map((issue) => (
            <li key={issue.message}>{issue.message}</li>
          ))}
        </ul>
      )}

      <Field label='步骤 ID' hint='稳定标识；改名后记得同步下游依赖与引用'>
        <Input
          value={step.step_id}
          onChange={(event) => onChange({ step_id: event.target.value })}
        />
      </Field>

      <Field label='名称'>
        <Input
          value={step.name}
          onChange={(event) => onChange({ name: event.target.value })}
        />
      </Field>

      <Field label='类型'>
        <Select
          value={step.kind}
          onValueChange={(value) =>
            // 切到 Agent 步骤时清空输入绑定：绑定只属于工具步骤，留着会在保存时
            // 被后端以「agent 步骤不得声明 input_bindings」直接拒绝。
            onChange(
              value === 'agent'
                ? { kind: value as WorkflowStepKind, bindings: [] }
                : { kind: value as WorkflowStepKind }
            )
          }
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value='agent'>Agent 步骤</SelectItem>
            <SelectItem value='tool'>工具步骤</SelectItem>
          </SelectContent>
        </Select>
      </Field>

      <Field label='上游依赖' hint='本步等这些步骤全部完成后才执行；空 = 起点'>
        {upstreamSteps.length === 0 ? (
          <p className='text-xs text-muted-foreground'>
            没有上游依赖，本步会在工作流开始时执行。
          </p>
        ) : (
          <div className='flex flex-wrap gap-1'>
            {upstreamSteps.map((upstream) => (
              <Button
                key={upstream.step_id}
                size='sm'
                variant='outline'
                onClick={() => onRemoveDependency(upstream.step_id.trim())}
              >
                {upstream.name || upstream.step_id} ✕
              </Button>
            ))}
          </div>
        )}
        {upstreamOptions.length > 0 && (
          <Select value='' onValueChange={(value) => onAddDependency(value)}>
            <SelectTrigger className='mt-2 w-full'>
              <SelectValue placeholder='添加上游依赖' />
            </SelectTrigger>
            <SelectContent>
              {upstreamOptions.map((candidate) => (
                <SelectItem
                  key={candidate.step_id}
                  value={candidate.step_id.trim()}
                >
                  {candidate.name || candidate.step_id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </Field>

      <Field
        label='步骤超时（秒）'
        hint='留空则用工作流级超时；填写时 30–7200 秒'
      >
        <Input
          type='number'
          value={step.timeout_seconds}
          onChange={(event) =>
            onChange({ timeout_seconds: event.target.value })
          }
        />
      </Field>

      <Field label='失败重试次数' hint='用同一份输入重试；用尽后失败策略才生效'>
        <Select
          value={String(step.max_retries)}
          onValueChange={(value) => onChange({ max_retries: Number(value) })}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {MAX_RETRIES_OPTIONS.map((count) => (
              <SelectItem key={count} value={String(count)}>
                {count === 0 ? '不重试' : `额外重试 ${count} 次`}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      {step.kind === 'agent' ? (
        <>
          <Field label='覆盖 Agent' hint='留空用工作流默认 Agent；必须同平台'>
            <Select
              value={
                step.agent_id != null
                  ? String(step.agent_id)
                  : NO_AGENT_OVERRIDE
              }
              onValueChange={(value) =>
                onChange({
                  agent_id: value === NO_AGENT_OVERRIDE ? null : Number(value),
                })
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_AGENT_OVERRIDE}>
                  使用工作流默认
                </SelectItem>
                {agentOptions.map((agent) => (
                  <SelectItem key={agent.id} value={String(agent.id)}>
                    {agent.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field
            label='指令'
            hint='可写 {{step_id.output}} 引用上游步骤的模型可见输出'
          >
            <Textarea
              rows={4}
              value={step.prompt}
              onChange={(event) => onChange({ prompt: event.target.value })}
              placeholder='这一步要 Agent 做什么，写成独立可执行的完整句子'
            />
          </Field>
        </>
      ) : (
        <>
          <Field label='工具名'>
            <Input
              value={step.tool_name}
              onChange={(event) => onChange({ tool_name: event.target.value })}
              placeholder='例如 sql_query'
            />
          </Field>

          <Field
            label='参数模板（JSON 对象）'
            hint='值里可写 {{step_id.output}} 引用上游步骤输出；留空表示无参数'
          >
            <Textarea
              className='font-mono'
              rows={4}
              value={step.tool_arguments_text}
              onChange={(event) =>
                onChange({ tool_arguments_text: event.target.value })
              }
              placeholder={'{\n  "keyword": "{{step_1.output}}"\n}'}
            />
          </Field>
        </>
      )}

      <Field label='失败策略'>
        <Select
          value={step.on_error}
          onValueChange={(value) =>
            onChange({ on_error: value as WorkflowStepOnError })
          }
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ON_ERROR_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      {step.on_error === 'continue_with_default' && (
        <Field
          label='兜底输出'
          hint='这一步失败时写进模型可见输出的内容，供后续步骤继续'
        >
          <Textarea
            rows={2}
            value={step.default_output}
            onChange={(event) =>
              onChange({ default_output: event.target.value })
            }
          />
        </Field>
      )}

      {/* 输入绑定只属于工具步骤：Agent 步骤通过提示词里的 {{步骤.output}} 取数，
          两种传值方式混用会被运行时静默忽略（后端也会在保存时直接拒绝）。 */}
      {step.kind === 'tool' && (
        <div>
          <Label>输入绑定</Label>
          <p className='mt-1 text-xs text-muted-foreground'>
            {referenceCandidates.length === 0
              ? '没有可选的上游步骤：先把别的步骤连到本步，或让本步依赖某个步骤。'
              : `把上游步骤的输出绑定成本步参数；输出路径目前只支持 ${OUTPUT_PATH}（即该步的模型可见输出）。`}
          </p>
          {step.bindings.map((binding, bindingIndex) => (
            <div
              key={bindingIndex}
              className='mt-2 flex flex-wrap items-center gap-2'
            >
              <Input
                className='w-32'
                placeholder='参数名'
                value={binding.key}
                onChange={(event) =>
                  onUpdateBinding(bindingIndex, { key: event.target.value })
                }
              />
              <Select
                value={binding.step_id || NO_PREVIOUS_STEP}
                onValueChange={(value) =>
                  onUpdateBinding(bindingIndex, {
                    step_id: value === NO_PREVIOUS_STEP ? '' : value,
                  })
                }
              >
                <SelectTrigger className='w-40'>
                  <SelectValue placeholder='引用步骤' />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_PREVIOUS_STEP}>未选择</SelectItem>
                  {referenceCandidates.map((candidate) => (
                    <SelectItem
                      key={candidate.step_id}
                      value={candidate.step_id.trim()}
                    >
                      {candidate.name || candidate.step_id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Input
                className='w-24'
                // 目前只有 output 一个合法取值（后端保存时强校验），做成只读，
                // 免得用户手输了别的值、保存时才被打回来。
                readOnly
                value={binding.path}
              />
              <Button
                size='sm'
                variant='outline'
                onClick={() => onRemoveBinding(bindingIndex)}
              >
                移除
              </Button>
            </div>
          ))}
          <Button
            size='sm'
            variant='outline'
            className='mt-2'
            onClick={onAddBinding}
          >
            添加绑定
          </Button>
        </div>
      )}
    </div>
  )
}

function Field({
  label,
  hint,
  className,
  children,
}: {
  label: string
  hint?: string
  className?: string
  children: React.ReactNode
}) {
  return (
    <div className={className}>
      <Label>{label}</Label>
      <div className='mt-1'>{children}</div>
      {hint && <p className='mt-1 text-xs text-muted-foreground'>{hint}</p>}
    </div>
  )
}
