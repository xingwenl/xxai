import { MAX_PARALLEL_BRANCHES } from '@/api/workflow'

/**
 * 画布用的最小步骤形状：只保留 DAG 结构相关的字段。
 * 让校验逻辑与表单草稿解耦，画布与表单可以各传各的结构。
 */
type DagStepLike = {
  step_id: string
  name: string
  /** 结构上的依赖来源；null 语义已在调用方折算成具体数组 */
  depends_on: string[] | null
}

/** 一条前端能定位到具体字段的校验问题：给节点飘红、给属性面板定位用。 */
export type DagIssue = {
  message: string
  /** 关联的步骤 id；无法定位到具体步骤时为 null */
  stepId: string | null
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
 * 校验一份 DAG 结构，口径与后端保存期强校验一致：
 * step_id 合法且唯一、依赖不能自引用/重复/悬空/成环、
 * 单层并行宽度不超过 MAX_PARALLEL_BRANCHES。
 *
 * 引用（input_bindings 与提示词里的 {{step.output}}）是否指向上游，
 * 需要知道每一步实际引用了谁，因此交给调用方通过 referencesOf 提供。
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

  steps.forEach((step, index) => {
    const stepId = step.step_id.trim()
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

  // 依赖自身的合法性：自引用、重复、悬空。
  resolved.forEach((deps, index) => {
    const stepId = steps[index].step_id.trim()
    const label = `步骤「${stepId || `#${index + 1}`}」`
    const seen = new Set<string>()
    deps.forEach((dep) => {
      if (dep === stepId) {
        issues.push({ message: `${label}不能依赖自己`, stepId })
      } else if (seen.has(dep)) {
        issues.push({ message: `${label}重复依赖「${dep}」`, stepId })
      } else if (!byStepId.has(dep)) {
        issues.push({ message: `${label}依赖了不存在的步骤「${dep}」`, stepId })
      }
      seen.add(dep)
    })
  })

  const structureBroken = issues.length > 0

  // 环检测 + 拓扑层（最长路径分层，与后端 Kahn 分层同口径）。
  const buckets = new Map<number, string[]>()
  const depth = new Map<string, number>()
  const reachable = new Map<string, Set<string>>()
  const stepIdList = steps.map((step) => step.step_id.trim())

  if (!structureBroken) {
    const indegree = new Map<string, number>()
    stepIdList.forEach((stepId) => indegree.set(stepId, 0))
    resolved.forEach((deps, index) => {
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
    resolved.forEach((deps, index) => {
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
    resolved.forEach((deps, index) => {
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

  if (referencesOf && !issues.some((issue) => issue.message.includes('成环'))) {
    steps.forEach((step, index) => {
      const stepId = step.step_id.trim()
      const upstream = reachable.get(stepId)
      if (!upstream) return
      const label = `步骤「${stepId || `#${index + 1}`}」`
      referencesOf(step, index).forEach((reference) => {
        const targetId = reference.stepId.trim()
        const where = reference.key
          ? `${label}的引用「${reference.key}」`
          : `${label}的引用`
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
        if (reference.path && reference.path !== 'output') {
          issues.push({
            message: `${where}的输出路径只能是 output，当前是「${reference.path}」`,
            stepId,
          })
        }
      })
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

/** 收集参数模板里的引用；供表单按「已解析的绑定 + 提示词 / 参数模板」组装引用列表。 */ export function collectTemplateReferences(
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
        (acc, dep) => Math.max(acc, (depth.get(dep) ?? 0) + 1),
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
