import { useMemo } from 'react'
import {
  MarkerType,
  type Edge,
  type Node,
  type NodeChange,
} from '@xyflow/react'
import {
  type ConditionBranch,
  type WorkflowNodePosition,
  type WorkflowStepKind,
  type WorkflowStepOnError,
} from '@/api/workflow'
import {
  DEFAULT_HANDLE,
  FAILED_HANDLE,
  baseStepId,
  branchHandle,
  declaredHandles,
  handleLabel,
} from '@/features/workflows/workflow-dag'

/**
 * 画布的数据层：节点/边的形状、拓扑自动布局、以及把画布交互折回草稿的辅助函数。
 * 拆成独立文件的原因有两条：一是这些函数不渲染任何东西，混在组件文件里会让
 * Fast Refresh 失效（react-refresh/only-export-components）；二是属性面板与
 * 画布组件都要用它们，放在中立位置避免互相 import。
 */

/** 自动布局的横向 / 纵向间距，按节点卡片尺寸留出连线走位空间。 */
const AUTO_LAYOUT_GAP_X = 280
const AUTO_LAYOUT_GAP_Y = 160

/** 首个节点之前的自动布局起点，避免新节点压在画布左上角。 */
const AUTO_LAYOUT_ORIGIN = { x: 80, y: 80 }

/**
 * 边 id 约定：与后端 definition.edges 的 edge_id 同形，便于对照。
 * 成功出口 `a->b`；具名出口（分支名 / failed）`a:分支名->b`。
 */
export function edgeId(
  source: string,
  target: string,
  handle: string = DEFAULT_HANDLE
) {
  return handle === DEFAULT_HANDLE
    ? `${source}->${target}`
    : `${source}:${handle}->${target}`
}

/** 节点右侧的一个出口（source handle）：id 就是出口名，条件步骤的每个分支各占一个。 */
export type CanvasSourceHandle = {
  id: string
  /** 出口的中文说明：成功 / 失败 / 分支名 */
  label: string
  /**
   * 出口的语义分档，用来决定连线与标签的配色：
   * default 成功出口、failed 失败出口、branch 条件分支出口。
   */
  tone: 'default' | 'branch' | 'failed'
}

/** 一个节点会渲染的出口集合；与保存期校验的「可用出口」共用 declaredHandles，避免两处口径漂移。 */
export function sourceHandlesOf(step: CanvasStepLike): CanvasSourceHandle[] {
  return declaredHandles(step).map((handle) => ({
    id: handle,
    label: handleLabel(handle),
    tone:
      handle === DEFAULT_HANDLE
        ? 'default'
        : handle === FAILED_HANDLE
          ? 'failed'
          : 'branch',
  }))
}

/** 节点 data：画布渲染需要的最小信息，其余字段都在属性面板里编辑。 */
export type WorkflowCanvasNodeData = {
  stepId: string
  name: string
  kind: WorkflowStepKind
  /** 该步骤当前命中的校验错误条数（0 表示无问题） */
  errorCount: number
  /** 右侧的出口列表：条件步骤每个分支一个，普通步骤成功出口（fail_branch 时多失败出口） */
  handles: CanvasSourceHandle[]
}

export type WorkflowCanvasNode = Node<WorkflowCanvasNodeData, 'workflowStep'>

/** 画布节点需要的最小步骤形状，只依赖结构字段，不绑定完整 step 类型。 */
type CanvasStepLike = {
  step_id: string
  name: string
  kind: WorkflowStepKind
  on_error: WorkflowStepOnError
  branches: ConditionBranch[] | null
  position: WorkflowNodePosition | null
}

/**
 * 自动布局：按依赖最长路径分层，从左到右摆放。
 * 只在后端还没给 position（存量线性定义）时兜底，用户拖过的位置不会被覆盖。
 * 依赖层级只看基础 step_id：同一上游的多个出口边不该把下游推到更右边。
 */
export function autoLayoutPositions(
  steps: { step_id: string }[],
  resolved: string[][]
): WorkflowNodePosition[] {
  const depth = new Map<string, number>()
  steps.forEach((step, index) => {
    const deps = resolved[index] ?? []
    // 依赖是“每个节点最多访问一次”的前向结构，取上游深度的最大值即可。
    const level =
      deps.length === 0
        ? 0
        : Math.max(...deps.map((dep) => (depth.get(baseStepId(dep)) ?? 0) + 1))
    depth.set(step.step_id, level)
  })
  const usedRows = new Map<number, number>()
  return steps.map((step) => {
    const level = depth.get(step.step_id) ?? 0
    const row = usedRows.get(level) ?? 0
    usedRows.set(level, row + 1)
    return {
      x: AUTO_LAYOUT_ORIGIN.x + level * AUTO_LAYOUT_GAP_X,
      y: AUTO_LAYOUT_ORIGIN.y + row * AUTO_LAYOUT_GAP_Y,
    }
  })
}

/** 由结构生成画布节点；位置优先用后端保存的 position，缺失时按拓扑层兜底。 */
export function buildCanvasNodes(
  steps: CanvasStepLike[],
  resolved: string[][],
  errorCountByStep: Map<string, number>
): WorkflowCanvasNode[] {
  const layout = autoLayoutPositions(steps, resolved)
  return steps.map((step, index) => ({
    id: step.step_id,
    type: 'workflowStep',
    data: {
      stepId: step.step_id,
      name: step.name,
      kind: step.kind,
      errorCount: errorCountByStep.get(step.step_id) ?? 0,
      handles: sourceHandlesOf(step),
    },
    position: step.position ?? layout[index],
  }))
}

/**
 * 由 depends_on 推导边集；连线只表示依赖先后，不代表数据流。
 *
 * 每条依赖条目都带出口后缀（缺省即成功出口），因此边必须带 sourceHandle，
 * 否则画布上「走失败出口」和「走成功出口」会画成同一根线。
 * 具名出口的线带分支名标签并换色，失败出口用虚线 + destructive 色，方便一眼分辨。
 */
export function buildCanvasEdges(
  resolved: string[][],
  stepIds: string[]
): Edge[] {
  const edges: Edge[] = []
  resolved.forEach((deps, index) => {
    const target = stepIds[index]
    deps.forEach((dep) => {
      const source = baseStepId(dep)
      const handle = branchHandle(dep)
      const named = handle !== DEFAULT_HANDLE
      const failed = handle === FAILED_HANDLE
      const color = failed ? 'var(--destructive)' : 'var(--chart-3)'
      edges.push({
        id: edgeId(source, target, handle),
        source,
        sourceHandle: handle,
        target,
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: named ? color : undefined,
        },
        label: named ? handleLabel(handle) : undefined,
        labelStyle: named
          ? { fill: color, fontSize: 11, fontWeight: 600 }
          : undefined,
        style: named
          ? {
              stroke: color,
              strokeWidth: 1.5,
              strokeDasharray: failed ? '4 3' : undefined,
            }
          : undefined,
      })
    })
  })
  return edges
}

/** 把 React Flow 的位置变更折算成步骤补丁，交给表单写回草稿。 */
export function positionPatchesFromChanges(
  changes: NodeChange<WorkflowCanvasNode>[]
): { stepId: string; position: WorkflowNodePosition }[] {
  const patches: { stepId: string; position: WorkflowNodePosition }[] = []
  changes.forEach((change) => {
    if (change.type !== 'position') return
    if (!change.position) return
    patches.push({ stepId: change.id, position: change.position })
  })
  return patches
}

/** 用 useMemo 缓存画布节点，避免每次表单输入都重建节点对象触发重渲染。 */
export function useCanvasNodes(
  steps: CanvasStepLike[],
  resolved: string[][],
  errorCountByStep: Map<string, number>
): WorkflowCanvasNode[] {
  return useMemo(
    () => buildCanvasNodes(steps, resolved, errorCountByStep),
    [steps, resolved, errorCountByStep]
  )
}

/** 同上，边集也缓存；resolved 每次渲染都是新数组，因此依赖它时必须同步 memo 化。 */
export function useCanvasEdges(
  resolved: string[][],
  stepIds: string[]
): Edge[] {
  return useMemo(() => buildCanvasEdges(resolved, stepIds), [resolved, stepIds])
}
