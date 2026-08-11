import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Database } from 'lucide-react'
import { toast } from 'sonner'
import {
  bindKnowledgeBaseAgent,
  listAgentKnowledgeBases,
  listKnowledgeBases,
  unbindKnowledgeBaseAgent,
} from '@/api/knowledge'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { AssociationToolbar } from './association-toolbar'

export function AgentKnowledgeTab({
  platformId,
  agentId,
}: {
  platformId?: number
  agentId: number
}) {
  const queryClient = useQueryClient()
  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState('all')
  const bindingsQuery = useQuery({
    queryKey: ['agent-knowledge-bindings', platformId, agentId],
    queryFn: () => listAgentKnowledgeBases(platformId!, agentId),
    enabled: platformId != null,
  })
  const basesQuery = useQuery({
    queryKey: ['knowledge-bases', platformId],
    queryFn: () => listKnowledgeBases(platformId!, { pageSize: 100 }),
    enabled: platformId != null,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ['agent-knowledge-bindings', platformId, agentId],
      }),
      queryClient.invalidateQueries({
        queryKey: ['agent', platformId, agentId],
      }),
    ])
  }
  const bindMutation = useMutation({
    mutationFn: (baseId: number) =>
      bindKnowledgeBaseAgent(platformId!, baseId, agentId),
    onSuccess: async () => {
      toast.success('知识库已关联')
      await invalidate()
    },
    onError: () => toast.error('关联失败，请重试'),
  })
  const unbindMutation = useMutation({
    mutationFn: (baseId: number) =>
      unbindKnowledgeBaseAgent(platformId!, agentId, baseId),
    onSuccess: async () => {
      toast.success('知识库已解除关联')
      await invalidate()
    },
    onError: () => toast.error('解除关联失败，请重试'),
  })
  const rows = useMemo(() => {
    const items = (basesQuery.data?.items ?? []).map((base) => ({
      base,
      binding: bindingsQuery.data?.find(
        (item) => item.knowledge_base_id === base.id
      ),
    }))
    const filtered = keyword
      ? items.filter(
          ({ base }) =>
            base.name.includes(keyword) || base.slug.includes(keyword)
        )
      : items
    if (status === 'bound') return filtered.filter(({ binding }) => binding)
    if (status === 'unbound') return filtered.filter(({ binding }) => !binding)
    return filtered
  }, [basesQuery.data, bindingsQuery.data, keyword, status])
  const busy = bindMutation.isPending || unbindMutation.isPending

  return (
    <div className='space-y-3'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <AssociationToolbar
          keyword={keyword}
          onKeywordChange={setKeyword}
          status={status}
          onStatusChange={setStatus}
        />
        <span className='text-sm text-muted-foreground'>
          已关联 {bindingsQuery.data?.length ?? 0} 个知识库 ·
          变更在下一轮对话生效
        </span>
      </div>
      {basesQuery.isLoading || bindingsQuery.isLoading ? (
        Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className='h-20 w-full' />
        ))
      ) : rows.length ? (
        rows.map(({ base, binding }) => (
          <div
            key={base.id}
            className='flex items-start justify-between gap-4 rounded-md border p-4'
          >
            <div className='flex min-w-0 gap-3'>
              <div className='flex size-9 shrink-0 items-center justify-center rounded-md bg-muted'>
                <Database className='size-4 text-muted-foreground' />
              </div>
              <div className='min-w-0 space-y-1'>
                <div className='flex flex-wrap items-center gap-2'>
                  <span className='font-medium'>{base.name}</span>
                  <Badge variant='outline'>{base.slug}</Badge>
                </div>
                <p className='text-sm text-muted-foreground'>
                  {base.embedding_model} · 索引版本 {base.active_index_version}
                </p>
              </div>
            </div>
            <div className='flex shrink-0 items-center gap-3'>
              <span className='text-xs text-muted-foreground'>
                {binding ? `${binding.document_count} 文档` : '未关联'}
              </span>
              <Switch
                aria-label={`${binding ? '解除' : '关联'} ${base.name}`}
                checked={!!binding}
                disabled={busy}
                onCheckedChange={(checked) =>
                  checked
                    ? bindMutation.mutate(base.id)
                    : unbindMutation.mutate(base.id)
                }
              />
            </div>
          </div>
        ))
      ) : (
        <div className='flex min-h-32 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground'>
          暂无知识库，请先到知识库管理创建。
        </div>
      )}
    </div>
  )
}
