import { useCallback } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
  type Edge,
  type NodeChange,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { AlertTriangle, GitBranch, Plus, Trash2 } from 'lucide-react'
import type { WorkflowStepKind } from '@/api/workflow'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
// 节点形状、布局与交互折算都在 model 文件里，这里只负责渲染。
import {
  type CanvasSourceHandle,
  type WorkflowCanvasNode,
} from '@/features/workflows/workflow-canvas-model'
import { DEFAULT_HANDLE } from '@/features/workflows/workflow-dag'

/** 步骤类型的中文标签，画布与属性面板共用同一套措辞。 */
const KIND_LABEL: Record<WorkflowStepKind, string> = {
  agent: 'Agent',
  tool: '工具',
  condition: '条件',
}

/** 出口圆点与标签的配色：成功出口跟随主色，分支出口用图表蓝，失败出口用 destructive 红。 */
function handleColor(tone: CanvasSourceHandle['tone']): string {
  if (tone === 'failed') return 'var(--destructive)'
  if (tone === 'branch') return 'var(--chart-3)'
  return 'var(--primary)'
}

/**
 * 自定义节点：左侧一个接入点，右侧每个「出口」一个连接点。
 *
 * 出口是本步真的会走到的地方：条件步骤每个分支一个（没有成功出口），
 * 普通步骤是「成功」，on_error=fail_branch 时多一个「失败」。
 * 连线必须挂在具体出口上，运行期才有「到达触发」可言。
 */
function WorkflowStepNode({ data, selected }: NodeProps<WorkflowCanvasNode>) {
  const hasError = data.errorCount > 0
  return (
    <div
      className={cn(
        'w-56 rounded-md border bg-card p-3 text-left shadow-sm transition-colors',
        selected && 'border-primary ring-2 ring-primary/30',
        hasError && 'border-destructive',
        !selected && !hasError && 'border-border'
      )}
    >
      <Handle type='target' position={Position.Left} />
      <div className='flex items-center justify-between gap-2'>
        <span className='truncate text-sm font-medium'>
          {data.name || data.stepId || '未命名步骤'}
        </span>
        <Badge
          variant={
            data.kind === 'agent'
              ? 'default'
              : data.kind === 'condition'
                ? 'outline'
                : 'secondary'
          }
        >
          {KIND_LABEL[data.kind]}
        </Badge>
      </div>
      <div className='mt-1 truncate font-mono text-xs text-muted-foreground'>
        {data.stepId || '（缺少 step_id）'}
      </div>
      {hasError && (
        <div className='mt-2 flex items-center gap-1 text-xs text-destructive'>
          <AlertTriangle className='size-3' />
          {data.errorCount} 处问题
        </div>
      )}
      <div className='mt-3 flex flex-col gap-1 border-t pt-2'>
        {data.handles.length === 0 ? (
          <span className='pr-1 text-right text-[11px] text-destructive'>
            还没有分支出口
          </span>
        ) : (
          data.handles.map((handle) => (
            // 每个出口自成一个 relative 行，Handle 会贴着该行右侧落位。
            <div
              key={handle.id}
              className='relative flex items-center justify-end gap-1 pr-1'
            >
              <Handle
                id={handle.id}
                type='source'
                position={Position.Right}
                className='!size-2.5 !border-background'
                style={{ backgroundColor: handleColor(handle.tone) }}
              />
              <span
                className='max-w-[9rem] truncate text-[11px]'
                style={{ color: handleColor(handle.tone) }}
                title={handle.label}
              >
                {handle.label}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

const nodeTypes = { workflowStep: WorkflowStepNode }

/**
 * 工作流 DAG 画布。
 *
 * 画布是「结构」的唯一编辑入口：节点位置写回 position，连线写回 depends_on。
 * 这里只负责结构与选中态，字段编辑交给右侧属性面板，避免把表单状态搬进画布。
 */
export function WorkflowCanvas({
  nodes,
  edges,
  selectedStepId,
  onSelect,
  onNodesChange,
  onConnect,
  onEdgesDelete,
  onAddStep,
  onDeleteStep,
}: {
  nodes: WorkflowCanvasNode[]
  edges: Edge[]
  selectedStepId: string | null
  onSelect: (stepId: string | null) => void
  onNodesChange: (changes: NodeChange<WorkflowCanvasNode>[]) => void
  /** handle 是连线的起点出口：成功 / 失败 / 分支名 */
  onConnect: (source: string, target: string, handle: string) => void
  onEdgesDelete: (edges: Edge[]) => void
  onAddStep: () => void
  onDeleteStep: (stepId: string) => void
}) {
  const handleConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return
      // 自环后端会直接拒绝，这里静默忽略，避免拖出一根立刻飘红的线。
      if (connection.source === connection.target) return
      // 单出口节点不带 handle id，缺省即成功出口。
      onConnect(
        connection.source,
        connection.target,
        connection.sourceHandle ?? DEFAULT_HANDLE
      )
    },
    [onConnect]
  )

  const handleEdgesDelete = useCallback(
    (removed: Edge[]) => onEdgesDelete(removed),
    [onEdgesDelete]
  )

  return (
    <div className='flex min-h-0 flex-1 flex-col'>
      <div className='flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2'>
        <div className='flex items-center gap-2 text-sm'>
          <GitBranch className='size-4 text-muted-foreground' />
          <span className='text-muted-foreground'>
            从节点右侧的出口（成功 / 失败 /
            分支）拖到另一个节点左侧即建立依赖；选中节点后在右侧编辑字段。
          </span>
        </div>
        <Button size='sm' variant='outline' onClick={onAddStep}>
          <Plus className='me-1 size-4' />
          新增步骤
        </Button>
      </div>

      {/* 画布必须有确定高度：React Flow 依赖父容器尺寸计算视口。 */}
      <div className='h-[560px] min-h-[420px] flex-1'>
        <ReactFlowProvider>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onConnect={handleConnect}
            onEdgesDelete={handleEdgesDelete}
            onNodeClick={(_, node) => onSelect(node.id)}
            onPaneClick={() => onSelect(null)}
            fitView
            // 网格吸附让手工拖出来的图保持整齐，也便于 position 值可复现。
            snapToGrid
            snapGrid={[16, 16]}
            deleteKeyCode={['Backspace', 'Delete']}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable className='!bg-muted' />
            <CanvasToolbar
              selectedStepId={selectedStepId}
              onDeleteStep={onDeleteStep}
            />
          </ReactFlow>
        </ReactFlowProvider>
      </div>
    </div>
  )
}

/** 画布右上角工具条：适应视图 + 删除当前选中步骤。 */
function CanvasToolbar({
  selectedStepId,
  onDeleteStep,
}: {
  selectedStepId: string | null
  onDeleteStep: (stepId: string) => void
}) {
  const { fitView } = useReactFlow()
  return (
    <Panel position='top-right' className='flex gap-1'>
      <Button
        size='sm'
        variant='outline'
        onClick={() => void fitView({ padding: 0.2, duration: 200 })}
      >
        适应视图
      </Button>
      {selectedStepId && (
        <Button
          size='sm'
          variant='destructive'
          onClick={() => onDeleteStep(selectedStepId)}
        >
          <Trash2 className='me-1 size-4' />
          删除步骤
        </Button>
      )}
    </Panel>
  )
}
