import {
  BRANCH_HANDLE_SEPARATOR,
  MAX_PARALLEL_BRANCHES,
  type ConditionComparisonPredicate,
  type ConditionPredicate,
  type WorkflowStepKind,
  type WorkflowStepOnError,
} from '@/api/workflow'

/**
 * 画布用的最小步骤形状：只保留 DAG 结构与条件步骤校验相关的字段。
 * 让校验逻辑与表单草稿解耦，画布与表单可以各传各的结构；
 * kind / branches / on_error 等只为条件步骤的出口推导与字段冲突校验服务，普通步骤可以不带。
 */
export type DagStepLike = {
  step_id: string
  name: string
  /** 结构上的依赖来源；null 语义已在调用方折算成具体数组 */
  depends_on: string[] | null
  kind?: WorkflowStepKind
  on_error?: WorkflowStepOnError
  /** 仅条件步骤：分支出口（分支名即出口名），恰好一个无条件兜底且排在最后 */
  branches?:
    | {
        name: string
        when?: ConditionPredicate | null
      }[]
    | null
  prompt?: string | null
  tool_name?: string | null
  agent_id?: number | null
  input_bindings?: Record<string, unknown> | null
  tool_arguments?: Record<string, unknown> | null
  default_output?: string | null
}

/** 一条前端能定位到具体字段的校验问题：给节点飘红、给属性面板定位用。 */
export type DagIssue = {
  message: string
  /** 关联的步骤 id；无法定位到具体步骤时为 null */
  stepId: string | null
}

/** 普通步骤成功时到达的出口；条件步骤没有这个出口，只有自己声明的分支名。 */
export const DEFAULT_HANDLE = 'default'
/** on_error=fail_branch 的步骤失败时到达的出口；其它步骤没有这个出口。 */
export const FAILED_HANDLE = 'failed'
/** 不能当分支名用的保留出口名：同名会让画布分不清「分支」与「成功 / 失败」。 */
export const RESERVED_HANDLES = [DEFAULT_HANDLE, FAILED_HANDLE]

/** 单个条件步骤的分支数上限，与后端 MAX_CONDITION_BRANCHES 对齐。 */
export const MAX_CONDITION_BRANCHES = 8
/** 组合谓词的子条件数上限与嵌套深度上限，与后端 MAX_PREDICATE_CHILDREN / MAX_PREDICATE_DEPTH 对齐。 */
export const MAX_PREDICATE_CHILDREN = 16
export const MAX_PREDICATE_DEPTH = 4
/** matches 正则的长度上限，与后端 MAX_REGEX_LENGTH 对齐。 */
export const MAX_REGEX_LENGTH = 200

/** 分支名的字符集与长度；与后端 step_id / 分支名口径一致。 */
const BRANCH_NAME_PATTERN = /^[A-Za-z0-9_-]{1,64}$/
/** 谓词 left 只接受「恰好一个 {{步骤ID.output}}」，并捕获其中的步骤 ID。 */
const PREDICATE_REFERENCE_PATTERN = /^\{\{\s*([A-Za-z0-9_-]+)\.output\s*\}\}$/
const COMPARISON_OPS = ['equals', 'contains', 'not_empty', 'matches']
const LOGICAL_OPS = ['all', 'any', 'not']

/**
 * 一条依赖条目的基础步骤 id：剥掉 @出口 后缀。
 * 「依赖谁」与「走哪条出口」是两件事：拓扑、环检测、祖先集合只按基础 id 计算，
 * 出口只决定运行期「到达触发」是否成立。
 */
export function baseStepId(entry: string): string {
  const trimmed = entry.trim()
  const at = trimmed.indexOf(BRANCH_HANDLE_SEPARATOR)
  return at < 0 ? trimmed : trimmed.slice(0, at)
}

/**
 * 一条依赖条目里的出口名；没写 @出口 等价于成功出口 default。
 * 空后缀（"a@"）会返回空串，交给校验明确拒绝，而不是悄悄当成 default。
 */
export function branchHandle(entry: string): string {
  const trimmed = entry.trim()
  const at = trimmed.indexOf(BRANCH_HANDLE_SEPARATOR)
  if (at < 0) return DEFAULT_HANDLE
  return trimmed.slice(at + 1)
}

/** 依赖条目的规范写法：成功出口省略 @default 后缀，具名出口保留；交互里比较两条依赖是否同一条时用它。 */
export function normalizeDependency(entry: string): string {
  const source = baseStepId(entry)
  const handle = branchHandle(entry)
  return handle === DEFAULT_HANDLE
    ? source
    : `${source}${BRANCH_HANDLE_SEPARATOR}${handle}`
}

/**
 * 由「上游步骤 + 出口」反推依赖条目。
 * 成功出口写成不带后缀的原样，存量定义保存后逐字不变。
 */
export function dependencyEntry(stepId: string, handle: string): string {
  return handle === DEFAULT_HANDLE
    ? stepId
    : `${stepId}${BRANCH_HANDLE_SEPARATOR}${handle}`
}

/**
 * 推导出口所需的最小形状：条件步骤看 branches，普通步骤看 on_error。
 * 画布节点、表单草稿与校验用的 DagStepLike 都满足它，出口口径只此一处。
 */
export type HandleSourceLike = {
  kind?: WorkflowStepKind
  on_error?: WorkflowStepOnError
  branches?: { name: string; when?: ConditionPredicate | null }[] | null
}

/**
 * 一个步骤真的会到达的出口集合：
 * 条件步骤只有自己声明的分支名（没有 default / failed）；普通步骤恒有 default，
 * 声明 on_error=fail_branch 时多一个 failed。
 */
export function declaredHandles(step: HandleSourceLike): string[] {
  if (step.kind === 'condition') {
    const branches = Array.isArray(step.branches) ? step.branches : []
    return branches.map((branch) => (branch?.name ?? '').trim()).filter(Boolean)
  }
  const handles = [DEFAULT_HANDLE]
  if (step.on_error === 'fail_branch') handles.push(FAILED_HANDLE)
  return handles
}

/** 出口名的中文说明；分支出口直接用分支名，画布与属性面板共用。 */
export function handleLabel(handle: string): string {
  if (handle === DEFAULT_HANDLE) return '成功'
  if (handle === FAILED_HANDLE) return '失败'
  return handle
}

/**
 * 把所有步骤的 depends_on 折成显式数组：
 * null 表示「依赖序列中的前一个步骤」（后端缺省语义），
 * 第一条没有前驱，折成 []
 */
export function resolveDependencies<T extends DagStepLike>(
  steps: T[]
): string[][] {
  return steps.map((step, index) => {
    if (step.depends_on != null) return [...step.depends_on]
    return index > 0 ? [steps[index - 1].step_id] : []
  })
}

/**
 * 步骤草稿 -> 待提交的 depends_on：与缺省语义等价的依赖仍写成 null，存量定义保存后形状不变。
 *
 * 两处能安全折成 null（后端 `resolve_depends_on` 的约定）：
 *   - 首步：`null` 与 `[]` 都是「没有前驱」，写 `null` 才让改造前的定义保存后逐字不变；
 *   - 第 i 步只依赖第 i-1 步：这正是缺省语义本身。
 * 其余情况必须写成显式数组 —— 尤其非首步的 `[]`（并行分支起点）与多依赖汇聚点，
 * 折成 null 会改变语义。
 *
 * 判断基准必须是前一个步骤的 id；拿 resolved[index - 1][0]（那是前一步自己的依赖）
 * 来比只有两步以内才成立。
 * 带出口后缀的条目（"a@failed"）永远不等于裸步骤 id，因此会被原样写回，出口不丢。
 */
export function toDependsOnWrite(
  resolved: string[][],
  stepIds: string[],
  index: number
): string[] | null {
  const deps = resolved[index]
  if (index === 0) {
    return deps.length === 0 ? null : deps
  }
  if (deps.length === 1 && deps[0] === stepIds[index - 1]) {
    return null
  }
  return deps
}

/**
 * 取一条引用指向的步骤 id 与输出路径。
 * 这里不要求冒号前后无空格、也不允许把路径再拆出点号：step_id 允许连字符，
 * 输出路径目前只有 output 一个合法值。
 */
function parseMention(raw: string): { stepId: string; path: string } | null {
  const trimmed = raw.trim()
  const dot = trimmed.indexOf('.')
  if (dot <= 0 || dot === trimmed.length - 1) return null
  return { stepId: trimmed.slice(0, dot), path: trimmed.slice(dot + 1) }
}

/** 递归收集 JSON 结构（参数模板）里 {{step_id.output}} 形式的引用。 */
function collectMentions(value: unknown, found: string[]): void {
  if (typeof value === 'string') {
    found.push(...extractMentions(value))
    return
  }
  if (Array.isArray(value)) {
    value.forEach((item) => collectMentions(item, found))
    return
  }
  if (value && typeof value === 'object') {
    Object.values(value as Record<string, unknown>).forEach((item) =>
      collectMentions(item, found)
    )
  }
}

/**
 * 抽取字符串里的 {{step_id.output}} 引用。
 * 返回的是花括号内的原文，路径合法性交给调用方按上下文判定。
 */
export function extractMentions(text: string | null | undefined): string[] {
  if (!text) return []
  const pattern = /\{\{\s*([A-Za-z0-9_-]+\.[^}\s]+)\s*\}\}/g
  const found: string[] = []
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text)) !== null) found.push(match[1])
  return found
}

/**
 * 条件步骤自身的形状校验：分支数量与命名、兜底分支的数量与位置、谓词结构，
 * 以及「条件步骤没有执行体」。
 *
 * 这一趟不依赖依赖图，因此在拓扑校验之前就能给出可定位的报错；
 * 谓词引用「是不是上游」要等祖先集合算完，由 validateDag 另外一趟校验。
 */
function validateConditionStep(
  step: DagStepLike,
  label: string,
  stepId: string,
  issues: DagIssue[]
): void {
  const branches = Array.isArray(step.branches) ? step.branches : []
  if (branches.length === 0) {
    issues.push({
      message: `${label}是条件步骤，至少要有一个分支出口`,
      stepId,
    })
  } else if (branches.length > MAX_CONDITION_BRANCHES) {
    issues.push({
      message: `${label}有 ${branches.length} 个分支，超过上限 ${MAX_CONDITION_BRANCHES}`,
      stepId,
    })
  }

  const names = new Set<string>()
  let fallbackIndex = -1
  let fallbackCount = 0

  branches.forEach((branch, index) => {
    const rawName = typeof branch?.name === 'string' ? branch.name.trim() : ''
    const branchLabel = `${label}的第 ${index + 1} 个分支`
    if (!rawName) {
      issues.push({ message: `${branchLabel}缺少分支名`, stepId })
    } else if (!BRANCH_NAME_PATTERN.test(rawName)) {
      issues.push({
        message: `${branchLabel}「${rawName}」的分支名只能由字母、数字、下划线、连字符组成，长度 1-64`,
        stepId,
      })
    } else if (RESERVED_HANDLES.includes(rawName)) {
      issues.push({
        message: `${branchLabel}「${rawName}」是保留出口名（default 表示成功、failed 表示失败），不能当分支名`,
        stepId,
      })
    }
    if (rawName && names.has(rawName)) {
      issues.push({ message: `${label}有重复的分支名「${rawName}」`, stepId })
    }
    names.add(rawName)

    if (branch?.when == null) {
      // when 为空即无条件兜底：它保证条件全不成立时这一步仍有出口。
      fallbackCount += 1
      if (fallbackIndex < 0) fallbackIndex = index
      if (fallbackCount > 1) {
        issues.push({
          message: `${label}只能有一个无条件兜底分支（when 留空），当前有 ${fallbackCount} 个`,
          stepId,
        })
      }
      return
    }
    validatePredicate(
      branch.when,
      `${branchLabel}「${rawName || `#${index + 1}`}」的谓词`,
      stepId,
      1,
      issues
    )
  })

  if (branches.length > 0 && fallbackCount === 0) {
    issues.push({
      message: `${label}必须恰好有一个无条件兜底分支（when 留空），否则条件全不成立时这一步没有出口可走`,
      stepId,
    })
  } else if (fallbackIndex >= 0 && fallbackIndex !== branches.length - 1) {
    issues.push({
      message: `${label}的兜底分支必须排在最后，当前在第 ${fallbackIndex + 1} 个`,
      stepId,
    })
  }

  // 条件步骤只做判定：带上任何执行体字段，后端保存期会直接 400。
  const conflicts: string[] = []
  if ((step.prompt ?? '').trim()) conflicts.push('prompt')
  if ((step.tool_name ?? '').trim()) conflicts.push('tool_name')
  if (step.agent_id != null) conflicts.push('agent_id')
  if ((step.default_output ?? '').trim()) conflicts.push('default_output')
  if (step.input_bindings && Object.keys(step.input_bindings).length > 0) {
    conflicts.push('input_bindings')
  }
  if (step.tool_arguments && Object.keys(step.tool_arguments).length > 0) {
    conflicts.push('tool_arguments')
  }
  if (step.on_error != null && step.on_error !== 'abort') {
    conflicts.push(`on_error=${step.on_error}（条件步骤只能是 abort）`)
  }
  if (conflicts.length > 0) {
    issues.push({
      message: `${label}是条件步骤，不能声明执行体字段：${conflicts.join('、')}`,
      stepId,
    })
  }
}

/**
 * 递归校验一个谓词：算子必须在已知集合里、比较算子与组合算子的形状不能混用、
 * 子条件数量与嵌套深度在界内、比较算子的 left 恰好一个 {{步骤ID.output}}、
 * right 按算子必填，matches 的正则要能被编译。
 */
function validatePredicate(
  predicate: ConditionPredicate | null | undefined,
  label: string,
  stepId: string,
  depth: number,
  issues: DagIssue[]
): void {
  if (!predicate || typeof predicate !== 'object') {
    issues.push({ message: `${label}不是合法的谓词结构`, stepId })
    return
  }
  const op = (predicate as { op?: string }).op ?? ''

  if (LOGICAL_OPS.includes(op)) {
    const children = (predicate as { children?: unknown }).children
    if (!Array.isArray(children) || children.length === 0) {
      issues.push({ message: `${label}的 ${op} 至少需要一个子条件`, stepId })
      return
    }
    if (op === 'not' && children.length !== 1) {
      issues.push({
        message: `${label}的 not 只能有一个子条件，当前有 ${children.length} 个`,
        stepId,
      })
    }
    if (children.length > MAX_PREDICATE_CHILDREN) {
      issues.push({
        message: `${label}的 ${op} 有 ${children.length} 个子条件，超过上限 ${MAX_PREDICATE_CHILDREN}`,
        stepId,
      })
    }
    if (depth >= MAX_PREDICATE_DEPTH) {
      // 再嵌一层就会超过后端的深度上限，先在这里挡住。
      issues.push({
        message: `${label}的嵌套层数已达上限 ${MAX_PREDICATE_DEPTH}，${op} 不能再带子条件`,
        stepId,
      })
      return
    }
    children.forEach((child, index) => {
      validatePredicate(
        child as ConditionPredicate,
        `${label}的第 ${index + 1} 个子条件`,
        stepId,
        depth + 1,
        issues
      )
    })
    return
  }

  if (!COMPARISON_OPS.includes(op)) {
    issues.push({ message: `${label}使用了未知算子「${op}」`, stepId })
    return
  }

  const comparison = predicate as ConditionComparisonPredicate
  // 只认真正的数组：后端 model_dump 会把省略的 children 补成 null，
  // 把 null 当「带了子条件」会误判成非法定义（读侧已在 api/workflow.ts 归一化）。
  if (Array.isArray((predicate as { children?: unknown }).children)) {
    issues.push({
      message: `${label}的 ${op} 是比较算子，不能带 children 子条件`,
      stepId,
    })
  }
  const left = typeof comparison.left === 'string' ? comparison.left.trim() : ''
  const right = typeof comparison.right === 'string' ? comparison.right : ''
  if (!left) {
    issues.push({ message: `${label}缺少 left 引用`, stepId })
  } else if (!PREDICATE_REFERENCE_PATTERN.test(left)) {
    issues.push({
      message: `${label}的 left 必须是恰好一个 {{步骤ID.output}} 形式的引用，当前是「${left}」`,
      stepId,
    })
  }
  if (op !== 'not_empty' && !right.trim()) {
    issues.push({ message: `${label}的 ${op} 必须填写 right 比较值`, stepId })
  }
  if (op === 'matches' && right.trim()) {
    if (right.length > MAX_REGEX_LENGTH) {
      issues.push({
        message: `${label}的 matches 正则长度 ${right.length} 超过上限 ${MAX_REGEX_LENGTH}`,
        stepId,
      })
    }
    try {
      // 前端先编译一次，把非法正则挡在提交前（后端保存期同样会拒）。
      new RegExp(right)
    } catch (error) {
      issues.push({
        message: `${label}的 matches 正则不合法：${(error as Error).message}`,
        stepId,
      })
    }
  }
}

/** 深度优先走一遍谓词，把每个比较算子的 left 原样交给回调。 */
function visitPredicate(
  predicate: ConditionPredicate,
  visit: (left: string) => void
): void {
  if (!predicate || typeof predicate !== 'object') return
  if (LOGICAL_OPS.includes((predicate as { op?: string }).op ?? '')) {
    const children = (predicate as { children?: unknown }).children
    if (Array.isArray(children)) {
      children.forEach((child) => visitPredicate(child, visit))
    }
    return
  }
  const left = (predicate as ConditionComparisonPredicate).left
  if (typeof left === 'string') visit(left.trim())
}

/**
 * 收集条件步骤各分支谓词里引用的步骤。
 * 只认结构合法的 {{步骤ID.output}}；非法形状已经由 validatePredicate 报过，不重复报。
 */
function collectPredicateReferences(
  step: DagStepLike
): { where: string; stepId: string }[] {
  const found: { where: string; stepId: string }[] = []
  const branches = Array.isArray(step.branches) ? step.branches : []
  branches.forEach((branch, index) => {
    if (!branch || branch.when == null) return
    const branchName = (branch.name ?? '').trim() || `#${index + 1}`
    const where = `分支「${branchName}」的谓词`
    visitPredicate(branch.when, (left) => {
      const match = PREDICATE_REFERENCE_PATTERN.exec(left)
      if (match) found.push({ where, stepId: match[1] })
    })
  })
  return found
}

/**
 * 校验一份 DAG 结构，口径与后端保存期强校验一致：
 * step_id 合法且唯一、依赖不能自引用/重复/悬空/成环、
 * 依赖条目声明的出口必须真的存在（@failed 只有 fail_branch 上游才有）、
 * 条件步骤的分支出口与谓词结构合法、谓词只能引用上游，
 * 单层并行宽度不超过 MAX_PARALLEL_BRANCHES。
 *
 * 普通步骤的引用（input_bindings 与提示词里的 {{step.output}}）是否指向上游，
 * 需要知道每一步实际引用了谁，因此交给调用方通过 referencesOf 提供；
 * 条件步骤谓词里的引用由本函数自己收集，不依赖调用方。
 */
export function validateDag(
  steps: DagStepLike[],
  referencesOf?: (
    step: DagStepLike,
    index: number
  ) => { key: string; stepId: string; path: string }[]
): DagIssue[] {
  const issues: DagIssue[] = []
  const resolved = resolveDependencies(steps)
  const byStepId = new Map<string, number>()
  const stepIdList = steps.map((step) => step.step_id.trim())

  steps.forEach((step, index) => {
    const stepId = stepIdList[index]
    const label = `第 ${index + 1} 步「${step.name.trim() || stepId || '未命名'}」`
    if (!stepId) {
      issues.push({ message: `${label}缺少步骤 ID`, stepId: null })
      return
    }
    if (byStepId.has(stepId)) {
      issues.push({
        message: `${label}的步骤 ID「${stepId}」重复`,
        stepId,
      })
      return
    }
    byStepId.set(stepId, index)
  })

  // 依赖条目的合法性：自引用、重复、悬空、出口是否存在。
  // 出口决定「到达触发」：引用一个上游不会走的出口，这条边永远到不了，必须在保存期挡住。
  resolved.forEach((deps, index) => {
    const stepId = stepIdList[index]
    const label = `步骤「${stepId || `#${index + 1}`}」`
    const seen = new Set<string>()
    deps.forEach((rawDep) => {
      const entry = String(rawDep ?? '').trim()
      const source = baseStepId(entry)
      const handle = branchHandle(entry)
      const where = `${label}的依赖「${entry}」`
      if (source === stepId) {
        issues.push({ message: `${label}不能依赖自己`, stepId })
        return
      }
      if (seen.has(entry)) {
        issues.push({ message: `${label}重复依赖「${entry}」`, stepId })
        return
      }
      seen.add(entry)
      if (!source) {
        issues.push({
          message: `${label}有一条缺少步骤 ID 的依赖条目「${entry}」`,
          stepId,
        })
        return
      }
      if (!byStepId.has(source)) {
        issues.push({
          message: `${where}指向了不存在的步骤「${source}」`,
          stepId,
        })
        return
      }
      if (!handle) {
        issues.push({
          message: `${where}的出口名为空：要么不写 ${BRANCH_HANDLE_SEPARATOR}，要么在它后面写分支名`,
          stepId,
        })
        return
      }
      const sourceStep = steps[byStepId.get(source)!]
      const available = declaredHandles(sourceStep)
      if (available.includes(handle)) return
      if (handle === FAILED_HANDLE) {
        issues.push({
          message: `${where}用了失败出口：只有 on_error 为 fail_branch 的上游才有 @${FAILED_HANDLE} 出口`,
          stepId,
        })
        return
      }
      issues.push({
        message: `${where}指向了上游「${source}」不存在的出口「${handle}」；它可用的出口：${available.join('、') || '（无）'}`,
        stepId,
      })
    })
  })

  const structureBroken = issues.length > 0

  // 条件步骤自身的形状（与依赖图无关），独立跑一趟，尽早给出可定位的报错。
  steps.forEach((step, index) => {
    if (step.kind !== 'condition') return
    const stepId = stepIdList[index]
    validateConditionStep(
      step,
      `步骤「${stepId || `#${index + 1}`}」`,
      stepId,
      issues
    )
  })

  // 拓扑只看「依赖谁」：同一上游的多个出口边（a 与 a@failed）在结构上是同一条依赖，
  // 按基础 step_id 去重后再算入度，否则同一条依赖会被重复计数。
  const baseDeps = resolved.map((deps) => {
    const unique = new Set<string>()
    deps.forEach((dep) => {
      const base = baseStepId(String(dep ?? ''))
      if (base) unique.add(base)
    })
    return [...unique]
  })

  // 环检测 + 拓扑层（最长路径分层，与后端 Kahn 分层同口径）。
  const buckets = new Map<number, string[]>()
  const depth = new Map<string, number>()
  const reachable = new Map<string, Set<string>>()

  if (!structureBroken) {
    const indegree = new Map<string, number>()
    stepIdList.forEach((stepId) => indegree.set(stepId, 0))
    baseDeps.forEach((deps, index) => {
      indegree.set(stepIdList[index], deps.length)
    })

    const queue: string[] = []
    stepIdList.forEach((stepId) => {
      if ((indegree.get(stepId) ?? 0) === 0) {
        depth.set(stepId, 0)
        queue.push(stepId)
      }
    })

    // 反向邻接：deps -> 依赖它的步骤，用来剥离入度。
    const dependents = new Map<string, string[]>()
    stepIdList.forEach((stepId) => dependents.set(stepId, []))
    baseDeps.forEach((deps, index) => {
      deps.forEach((dep) => dependents.get(dep)?.push(stepIdList[index]))
    })

    let settled = 0
    while (queue.length > 0) {
      const current = queue.shift()!
      settled += 1
      const currentDepth = depth.get(current) ?? 0
      for (const next of dependents.get(current) ?? []) {
        // 汇聚节点取最深的那个上游，保证它落在所有上游之后。
        depth.set(next, Math.max(depth.get(next) ?? 0, currentDepth + 1))
        const left = (indegree.get(next) ?? 0) - 1
        indegree.set(next, left)
        if (left === 0) queue.push(next)
      }
    }

    if (settled < stepIdList.length) {
      const inCycle = stepIdList.filter((stepId) => !depth.has(stepId))
      issues.push({
        message: `步骤之间的依赖成环，环上的步骤：${inCycle.join('、')}`,
        stepId: inCycle[0] ?? null,
      })
    } else {
      stepIdList.forEach((stepId) => {
        const level = depth.get(stepId) ?? 0
        buckets.set(level, [...(buckets.get(level) ?? []), stepId])
      })
    }
  }

  if (
    !structureBroken &&
    !issues.some((issue) => issue.message.includes('成环'))
  ) {
    for (const [level, members] of buckets) {
      if (members.length > MAX_PARALLEL_BRANCHES) {
        issues.push({
          message: `第 ${level + 1} 层有 ${members.length} 个步骤可以并行执行，超过上限 ${MAX_PARALLEL_BRANCHES}：${members.join('、')}`,
          stepId: null,
        })
      }
    }

    // 反向可达集：用来回答「引用的是不是上游（直接或间接依赖）」。
    const reverse = new Map<string, string[]>()
    stepIdList.forEach((stepId) => reverse.set(stepId, []))
    baseDeps.forEach((deps, index) => {
      const stepId = stepIdList[index]
      deps.forEach((dep) => reverse.get(stepId)?.push(dep))
    })
    stepIdList.forEach((stepId) => {
      const upstream = new Set<string>()
      const stack = [...(reverse.get(stepId) ?? [])]
      while (stack.length > 0) {
        const current = stack.pop()!
        if (upstream.has(current)) continue
        upstream.add(current)
        stack.push(...(reverse.get(current) ?? []))
      }
      reachable.set(stepId, upstream)
    })
  }

  if (!issues.some((issue) => issue.message.includes('成环'))) {
    steps.forEach((step, index) => {
      const stepId = stepIdList[index]
      const upstream = reachable.get(stepId)
      if (!upstream) return
      const label = `步骤「${stepId || `#${index + 1}`}」`
      const checkReference = (
        where: string,
        targetId: string,
        path: string
      ) => {
        if (!byStepId.has(targetId)) {
          issues.push({
            message: `${where}指向了不存在的步骤「${targetId}」`,
            stepId,
          })
          return
        }
        if (!upstream.has(targetId)) {
          issues.push({
            message: `${where}只能指向上游步骤，「${targetId}」不是它的（直接或间接）上游`,
            stepId,
          })
        }
        if (path && path !== 'output') {
          issues.push({
            message: `${where}的输出路径只能是 output，当前是「${path}」`,
            stepId,
          })
        }
      }

      if (referencesOf) {
        referencesOf(step, index).forEach((reference) => {
          const where = reference.key
            ? `${label}的引用「${reference.key}」`
            : `${label}的引用`
          checkReference(where, reference.stepId.trim(), reference.path)
        })
      }
      // 条件步骤的谓词读的是上游输出，引用同样只能指向上游。
      if (step.kind === 'condition') {
        collectPredicateReferences(step).forEach((reference) => {
          checkReference(
            `${label}的${reference.where}`,
            reference.stepId,
            'output'
          )
        })
      }
    })
  }

  // 同一条规则可能对同一对节点各报一次，去重后再展示。
  const seen = new Set<string>()
  return issues.filter((issue) => {
    const key = `${issue.stepId ?? ''}|${issue.message}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

/** 收集参数模板里的引用；供表单按「已解析的绑定 + 提示词 / 参数模板」组装引用列表。 */
export function collectTemplateReferences(
  prompt: string | null | undefined,
  toolArguments: unknown
): { stepId: string; path: string }[] {
  const found: string[] = []
  collectMentions(prompt ?? '', found)
  collectMentions(toolArguments, found)
  return found
    .map(parseMention)
    .filter((item): item is { stepId: string; path: string } => item !== null)
}

/**
 * 汇总一份 DAG 的形状：并行层数与最宽层。
 * 详情页用它向用户解释「这条工作流会并发跑多少步」，口径与校验里的分层一致。
 */
export function dagShape(steps: DagStepLike[]): {
  layers: number
  maxWidth: number
} {
  const resolved = resolveDependencies(steps)
  const depth = new Map<string, number>()
  steps.forEach((step) => depth.set(step.step_id, 0))

  // 用松弛法求最长依赖链：valid DAG 在 n 轮内收敛，存在环时只是显示值不准，
  // 环本身由 validateDag 明确报错。
  for (let pass = 0; pass < steps.length; pass += 1) {
    let changed = false
    resolved.forEach((deps, index) => {
      const current = depth.get(steps[index].step_id) ?? 0
      const next = deps.reduce(
        (acc, dep) =>
          Math.max(acc, (depth.get(baseStepId(String(dep ?? ''))) ?? 0) + 1),
        0
      )
      if (next > current) {
        depth.set(steps[index].step_id, next)
        changed = true
      }
    })
    if (!changed) break
  }

  const buckets = new Map<number, number>()
  depth.forEach((level) => buckets.set(level, (buckets.get(level) ?? 0) + 1))
  const widths = [...buckets.values()]
  return {
    layers: buckets.size,
    maxWidth: widths.length > 0 ? Math.max(...widths) : 0,
  }
}
