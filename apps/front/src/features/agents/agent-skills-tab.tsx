import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileCode2 } from 'lucide-react'
import { toast } from 'sonner'
import {
  bindSkill,
  listAgentSkills,
  listSkills,
  unbindSkill,
} from '@/api/skills'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { AssociationToolbar } from './association-toolbar'

export function AgentSkillsTab({
  platformId,
  agentId,
}: {
  platformId?: number
  agentId: number
}) {
  const queryClient = useQueryClient()
  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState('all')
  const skillsQuery = useQuery({
    queryKey: ['skills', platformId],
    queryFn: () => listSkills(platformId!, { pageSize: 100 }),
    enabled: platformId != null,
  })
  const bindingsQuery = useQuery({
    queryKey: ['agent-skill-bindings', platformId, agentId],
    queryFn: () => listAgentSkills(platformId!, agentId),
    enabled: platformId != null,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ['agent-skill-bindings', platformId, agentId],
      }),
      queryClient.invalidateQueries({
        queryKey: ['agent', platformId, agentId],
      }),
    ])
  }
  const bindMutation = useMutation({
    mutationFn: (skillId: number) => bindSkill(platformId!, agentId, skillId),
    onSuccess: async () => {
      toast.success('技能已关联')
      await invalidate()
    },
    onError: () => toast.error('关联失败，请重试'),
  })
  const unbindMutation = useMutation({
    mutationFn: (skillId: number) => unbindSkill(platformId!, agentId, skillId),
    onSuccess: async () => {
      toast.success('技能已解除关联')
      await invalidate()
    },
    onError: () => toast.error('解除关联失败，请重试'),
  })
  const rows = useMemo(() => {
    const items = (skillsQuery.data?.items ?? []).map((skill) => ({
      skill,
      binding: bindingsQuery.data?.find((item) => item.skill_id === skill.id),
    }))
    const filtered = keyword
      ? items.filter(
          ({ skill }) =>
            skill.name.includes(keyword) || skill.slug.includes(keyword)
        )
      : items
    if (status === 'bound') return filtered.filter(({ binding }) => binding)
    if (status === 'unbound') return filtered.filter(({ binding }) => !binding)
    return filtered
  }, [skillsQuery.data, bindingsQuery.data, keyword, status])
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
          已关联 {bindingsQuery.data?.length ?? 0} 个技能 · 变更在下一轮对话生效
        </span>
      </div>
      {skillsQuery.isLoading || bindingsQuery.isLoading ? (
        Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className='h-20 w-full' />
        ))
      ) : rows.length ? (
        rows.map(({ skill, binding }) => (
          <div
            key={skill.id}
            className='flex items-start justify-between gap-4 rounded-md border p-4'
          >
            <div className='flex min-w-0 gap-3'>
              <div className='flex size-9 shrink-0 items-center justify-center rounded-md bg-muted'>
                <FileCode2 className='size-4 text-muted-foreground' />
              </div>
              <div className='min-w-0 space-y-1'>
                <div className='flex flex-wrap items-center gap-2'>
                  <span className='font-medium'>{skill.name}</span>
                  <Badge variant={skill.is_active ? 'outline' : 'secondary'}>
                    {skill.is_active ? '启用' : '停用'}
                  </Badge>
                  <Badge variant='outline'>
                    {skill.package_id ? '技能包' : '自定义'}
                  </Badge>
                </div>
                <p className='text-sm text-muted-foreground'>
                  {skill.description || skill.slug}
                </p>
              </div>
            </div>
            <Switch
              aria-label={`${binding ? '解除' : '关联'} ${skill.name}`}
              checked={!!binding}
              disabled={busy}
              onCheckedChange={(checked) =>
                checked
                  ? bindMutation.mutate(skill.id)
                  : unbindMutation.mutate(skill.id)
              }
            />
          </div>
        ))
      ) : (
        <div className='flex min-h-32 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground'>
          暂无技能，请先到技能管理创建。
        </div>
      )}
    </div>
  )
}
