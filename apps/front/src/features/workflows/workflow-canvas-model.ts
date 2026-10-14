import { useMemo } from 'react'
import {
  MarkerType,
  type Edge,
  type Node,
  type NodeChange,
} from '@xyflow/react'
import {
  type WorkflowNodePosition,
  type WorkflowStepKind,
} from '@/api/workflow'

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

/** 边 id 约定：与后端 definition.edges 的 edge_id 同形，便于对照。 */
export function edgeId(source: string, target: string) {
  return `${source}->${target}`
}

/** 节点 data：画布渲染需要的最小信息，其余字段都在属性面板里编辑。 */
export type WorkflowCanvasNodeData = {
  stepId: string
  name: string
  kind: WorkflowStepKind
  /** 该步骤当前命中的校验错误条数（0 表示无问题） */
  errorCount: number
}

export type WorkflowCanvasNode = Node<WorkflowCanvasNodeData, 'workflowStep'>

/** 画布节点需要的最小步骤形状，只依赖结构字段，不绑定完整 step 类型。 */
type CanvasStepLike = {
  step_id: string
  name: string
  kind: WorkflowStepKind
  position: WorkflowNodePosition | null
}

/**
 * 自动布局：按依赖最长路径分层，从左到右摆放。
 * 只在后端还没给 position（存量线性定义）时兜底，用户拖过的位置不会被覆盖。
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
        : Math.max(...deps.map((dep) => (depth.get(dep) ?? 0) + 1))
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
    },
    position: step.position ?? layout[index],
  }))
}

/** 由 depends_on 推导边集；连线只表示依赖先后，不代表数据流。 */
export function buildCanvasEdges(
  resolved: string[][],
  stepIds: string[]
): Edge[] {
  return resolved.flatMap((deps, index) =>
    deps.map((dep) => ({
      id: edgeId(dep, stepIds[index]),
      source: dep,
      target: stepIds[index],
      markerEnd: { type: MarkerType.ArrowClosed },
    }))
  )
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
