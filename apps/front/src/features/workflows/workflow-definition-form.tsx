import { useState } from 'react'
import {
  type Workflow,
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

function toStepDraft(step: WorkflowStepWrite): StepDraft {
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
  }
}

function toDraft(workflow: Workflow): DefinitionDraft {
  return {
    name: workflow.name,
    description: workflow.description ?? '',
    agent_id: workflow.agent_id,
    max_steps: workflow.max_steps,
    timeout_seconds: workflow.timeout_seconds,
    auto_approve: workflow.auto_approve,
    strict_approval: workflow.strict_approval,
    steps: workflow.steps.map(toStepDraft),
  }
}

function newStepDraft(seq: number): StepDraft {
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
 * 保存前的静态校验，口径与后端一致：
 * step_id 非空且唯一、绑定只能指向排在前面的步骤、步骤数不超过上限。
 * 校验通过后才会发请求，避免用户反复等一次失败往返。
 */
function validateDraft(draft: DefinitionDraft): string[] {
  const errors: string[] = []
  if (!draft.name.trim()) errors.push('请填写工作流名称')
  if (!draft.agent_id) errors.push('请选择默认智能体')
  if (draft.steps.length === 0) errors.push('至少需要一个步骤')
  if (draft.steps.length > draft.max_steps) {
    errors.push(`步骤数 ${draft.steps.length} 超过上限 ${draft.max_steps}`)
  }
  if (draft.timeout_seconds < 30) errors.push('整条超时不能小于 30 秒')

  const seen = new Set<string>()
  draft.steps.forEach((step, index) => {
    const label = `第 ${index + 1} 步`
    const stepId = step.step_id.trim()
    if (!stepId) {
      errors.push(`${label}缺少步骤 ID`)
    } else if (seen.has(stepId)) {
      errors.push(`${label}的步骤 ID「${stepId}」重复`)
    } else if (!/^[A-Za-z0-9_-]+$/.test(stepId)) {
      errors.push(`${label}的步骤 ID 只能包含字母、数字、下划线和连字符`)
    }
    seen.add(stepId)

    if (!step.name.trim()) errors.push(`${label}缺少名称`)
    if (step.kind === 'agent' && !step.prompt.trim()) {
      errors.push(`${label}是 Agent 步骤，必须填写指令`)
    }
    if (step.kind === 'tool') {
      if (!step.tool_name.trim())
        errors.push(`${label}是工具步骤，必须填写工具名`)
      try {
        parseToolArguments(step.tool_arguments_text)
      } catch (error) {
        errors.push(`${label}的参数模板不是合法 JSON 对象：${String(error)}`)
      }
    }
    if (step.timeout_seconds.trim()) {
      const seconds = Number(step.timeout_seconds)
      if (!Number.isFinite(seconds) || seconds < 1) {
        errors.push(`${label}的步骤超时必须是正整数秒`)
      }
    }
    if (
      !Number.isInteger(step.max_retries) ||
      step.max_retries < 0 ||
      step.max_retries > MAX_RETRIES_OPTIONS.length - 1
    ) {
      errors.push(
        `${label}的重试次数必须是 0 到 ${MAX_RETRIES_OPTIONS.length - 1} 之间的整数`
      )
    }

    Object.entries(groupBindings(step)).forEach(([key, binding]) => {
      const targetIndex = draft.steps.findIndex(
        (item) => item.step_id.trim() === binding[0]
      )
      if (targetIndex < 0) {
        errors.push(`${label}的参数「${key}」引用了不存在的步骤 ${binding[0]}`)
      } else if (targetIndex >= index) {
        errors.push(`${label}的参数「${key}」只能引用排在前面的步骤`)
      }
      if (!binding[1]) {
        errors.push(`${label}的参数「${key}」缺少输出路径`)
      } else if (binding[1] !== OUTPUT_PATH) {
        // 运行期只发布这一个输出名，别的取值保存后必然跑不通，提前拦下。
        errors.push(
          `${label}的参数「${key}」输出路径只能是 ${OUTPUT_PATH}，当前是 ${binding[1]}`
        )
      }
    })
  })

  return errors
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

function toStepWrite(step: StepDraft): WorkflowStepWrite {
  return {
    step_id: step.step_id.trim(),
    name: step.name.trim(),
    kind: step.kind,
    agent_id: step.kind === 'agent' ? step.agent_id : null,
    prompt: step.kind === 'agent' ? step.prompt.trim() || null : null,
    tool_name: step.kind === 'tool' ? step.tool_name.trim() || null : null,
    tool_arguments:
      step.kind === 'tool'
        ? parseToolArguments(step.tool_arguments_text)
        : null,
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
  }
}

/**
 * 工作流定义编辑器：基本信息 + 表单式有序步骤列表。
 *
 * v1 明确不做画布 / 拖拽 / DAG，顺序只由「上移 / 下移」调整；
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
  const [errors, setErrors] = useState<string[]>([])

  function updateStep(index: number, patch: Partial<StepDraft>) {
    setDraft((prev) => ({
      ...prev,
      steps: prev.steps.map((step, i) =>
        i === index ? { ...step, ...patch } : step
      ),
    }))
  }

  function moveStep(index: number, offset: number) {
    setDraft((prev) => {
      const target = index + offset
      if (target < 0 || target >= prev.steps.length) return prev
      const steps = [...prev.steps]
      const [moved] = steps.splice(index, 1)
      steps.splice(target, 0, moved)
      return { ...prev, steps }
    })
  }

  function removeStep(index: number) {
    setDraft((prev) => ({
      ...prev,
      steps: prev.steps.filter((_, i) => i !== index),
    }))
  }

  function addStep() {
    setDraft((prev) => {
      // 新步骤的默认 id 必须避开已有步骤，否则保存时会被唯一性校验拦下。
      let seq = prev.steps.length + 1
      while (prev.steps.some((step) => step.step_id === `step_${seq}`)) seq += 1
      return { ...prev, steps: [...prev.steps, newStepDraft(seq)] }
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
    setDraft((prev) => ({
      ...prev,
      steps: prev.steps.map((step, i) =>
        i === index
          ? {
              ...step,
              bindings: [
                ...step.bindings,
                // 路径预填唯一合法值，省得用户对着「输出路径」想填什么。
                { key: '', step_id: '', path: OUTPUT_PATH },
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
    const nextErrors = validateDraft(draft)
    setErrors(nextErrors)
    if (nextErrors.length > 0) return
    onSubmit({
      name: draft.name.trim(),
      description: draft.description.trim() || null,
      agent_id: draft.agent_id,
      max_steps: draft.max_steps,
      steps: draft.steps.map(toStepWrite),
      timeout_seconds: draft.timeout_seconds,
      auto_approve: draft.auto_approve,
      strict_approval: draft.strict_approval,
    })
  }

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

      <div className='flex flex-wrap items-center justify-between gap-2'>
        <div>
          <h2 className='text-lg font-semibold'>步骤</h2>
          <p className='text-sm text-muted-foreground'>
            按顺序执行，每步各开一轮独立上下文；引用只能指向排在前面的步骤。
          </p>
        </div>
        <Button variant='outline' onClick={addStep}>
          添加步骤
        </Button>
      </div>

      {draft.steps.length === 0 && (
        <p className='rounded-md border p-3 text-sm text-muted-foreground'>
          还没有步骤，点「添加步骤」开始定义。
        </p>
      )}

      {draft.steps.map((step, index) => (
        <StepCard
          key={index}
          index={index}
          step={step}
          steps={draft.steps}
          agents={agents}
          isFirst={index === 0}
          isLast={index === draft.steps.length - 1}
          onChange={(patch) => updateStep(index, patch)}
          onMove={(offset) => moveStep(index, offset)}
          onRemove={() => removeStep(index)}
          onAddBinding={() => addBinding(index)}
          onUpdateBinding={(bindingIndex, patch) =>
            updateBinding(index, bindingIndex, patch)
          }
          onRemoveBinding={(bindingIndex) => removeBinding(index, bindingIndex)}
        />
      ))}

      {errors.length > 0 && (
        <ul className='flex flex-col gap-1 rounded-md border border-destructive/50 p-3 text-xs text-destructive'>
          {errors.map((error) => (
            <li key={error}>{error}</li>
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

/** 单个步骤卡片：上下移动调整顺序，kind 决定要填哪一组字段。 */
function StepCard({
  index,
  step,
  steps,
  agents,
  isFirst,
  isLast,
  onChange,
  onMove,
  onRemove,
  onAddBinding,
  onUpdateBinding,
  onRemoveBinding,
}: {
  index: number
  step: StepDraft
  steps: StepDraft[]
  agents: { id: number; name: string }[]
  isFirst: boolean
  isLast: boolean
  onChange: (patch: Partial<StepDraft>) => void
  onMove: (offset: number) => void
  onRemove: () => void
  onAddBinding: () => void
  onUpdateBinding: (
    bindingIndex: number,
    patch: Partial<StepDraft['bindings'][number]>
  ) => void
  onRemoveBinding: (bindingIndex: number) => void
}) {
  // 覆盖的 Agent 可能已被删除或不在当前列表里，补一个只读选项避免下拉框显示空白。
  const agentOptions = [...agents]
  if (
    step.agent_id != null &&
    !agentOptions.some((a) => a.id === step.agent_id)
  ) {
    agentOptions.push({ id: step.agent_id, name: `#${step.agent_id}` })
  }
  const previousSteps = steps.slice(0, index)

  return (
    <div className='rounded-md border p-3'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <div className='flex items-center gap-2'>
          <span className='text-sm font-medium'>第 {index + 1} 步</span>
          <Badge variant='outline'>
            {step.kind === 'agent' ? 'Agent 步骤' : '工具步骤'}
          </Badge>
          <span className='text-xs text-muted-foreground'>{step.step_id}</span>
        </div>
        <div className='flex gap-1'>
          <Button
            size='sm'
            variant='outline'
            disabled={isFirst}
            onClick={() => onMove(-1)}
          >
            上移
          </Button>
          <Button
            size='sm'
            variant='outline'
            disabled={isLast}
            onClick={() => onMove(1)}
          >
            下移
          </Button>
          <Button size='sm' variant='destructive' onClick={onRemove}>
            删除
          </Button>
        </div>
      </div>

      <div className='mt-3 grid gap-3 sm:grid-cols-2'>
        <Field label='步骤 ID' hint='稳定标识，后续步骤用它引用本步输出'>
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

        <Field label='步骤超时（秒）' hint='留空则用工作流级超时'>
          <Input
            type='number'
            value={step.timeout_seconds}
            onChange={(event) =>
              onChange({ timeout_seconds: event.target.value })
            }
          />
        </Field>

        <Field
          label='失败重试次数'
          hint='用同一份输入重试；用尽后失败策略才生效'
        >
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
                    agent_id:
                      value === NO_AGENT_OVERRIDE ? null : Number(value),
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
              className='sm:col-span-2'
              hint='可写 {{step_id.path}} 引用前序步骤的模型可见输出'
            >
              <Textarea
                rows={3}
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
                onChange={(event) =>
                  onChange({ tool_name: event.target.value })
                }
                placeholder='例如 sql_query'
              />
            </Field>

            <Field
              label='参数模板（JSON 对象）'
              className='sm:col-span-2'
              hint='值里可写 {{step_id.path}} 引用前序步骤输出；留空表示无参数'
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
            className='sm:col-span-2'
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
      </div>

      {/* 输入绑定只属于工具步骤：Agent 步骤通过提示词里的 {{步骤.output}} 取数，
          两种传值方式混用会被运行时静默忽略（后端也会在保存时直接拒绝）。 */}
      {step.kind === 'tool' && (
        <div className='mt-4'>
          <Label>输入绑定</Label>
          <p className='mt-1 text-xs text-muted-foreground'>
            {previousSteps.length === 0
              ? '第一步没有前序步骤，通常不需要绑定。'
              : `把前序步骤的输出绑定成本步参数；输出路径目前只支持 ${OUTPUT_PATH}（即该步的模型可见输出），后端保存时也只接受这一个值。`}
          </p>
          {step.bindings.map((binding, bindingIndex) => (
            <div
              key={bindingIndex}
              className='mt-2 flex flex-wrap items-center gap-2'
            >
              <Input
                className='w-40'
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
                <SelectTrigger className='w-48'>
                  <SelectValue placeholder='引用步骤' />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_PREVIOUS_STEP}>未选择</SelectItem>
                  {previousSteps.map((previous) => (
                    <SelectItem key={previous.step_id} value={previous.step_id}>
                      {previous.name || previous.step_id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Input
                className='w-40'
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
