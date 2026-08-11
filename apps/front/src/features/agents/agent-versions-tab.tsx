import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { History, Plus, Rocket, RotateCcw } from 'lucide-react'
import { toast } from 'sonner'
import {
  getAgent,
  listAgentVersions,
  publishAgentVersion,
  rollbackAgentVersion,
} from '@/api/agent'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { AgentVersionForm } from './agent-version-form'

export function AgentVersionsTab({
  platformId,
  agentId,
}: {
  platformId?: number
  agentId: number
}) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const agentQuery = useQuery({
    queryKey: ['agent', platformId, agentId],
    queryFn: () => getAgent(platformId!, agentId),
    enabled: platformId != null,
  })
  const versionsQuery = useQuery({
    queryKey: ['agent-versions', platformId, agentId],
    queryFn: () => listAgentVersions(platformId!, agentId),
    enabled: platformId != null,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ['agent-versions', platformId, agentId],
      }),
      queryClient.invalidateQueries({
        queryKey: ['agent', platformId, agentId],
      }),
    ])
  }
  const publishMutation = useMutation({
    mutationFn: (versionId: number) =>
      publishAgentVersion(platformId!, agentId, versionId),
    onSuccess: async () => {
      toast.success('版本已发布')
      await invalidate()
    },
  })
  const rollbackMutation = useMutation({
    mutationFn: (versionId: number) =>
      rollbackAgentVersion(platformId!, agentId, versionId),
    onSuccess: async () => {
      toast.success('版本已回滚')
      await invalidate()
    },
  })
  const currentVersionId = agentQuery.data?.default_version_id
  const versions = versionsQuery.data ?? []

  return (
    <Card className='rounded-md py-4'>
      <CardHeader className='border-b px-4 py-4'>
        <div className='flex items-center justify-between gap-2'>
          <div>
            <CardTitle className='text-base'>版本列表</CardTitle>
            <div className='mt-1 text-xs text-muted-foreground'>
              发布版本后立即作用于下一轮对话。
            </div>
          </div>
          <Button size='sm' onClick={() => setCreating((value) => !value)}>
            <Plus className='me-2 size-4' />
            新建版本
          </Button>
        </div>
      </CardHeader>
      <CardContent className='px-0 pt-0'>
        {creating && (
          <div className='border-b px-4 py-4'>
            <AgentVersionForm
              platformId={platformId}
              agentId={agentId}
              onCreated={() => setCreating(false)}
            />
          </div>
        )}
        <div className='overflow-x-auto'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>版本</TableHead>
                <TableHead>模型</TableHead>
                <TableHead>Temperature</TableHead>
                <TableHead>API Key</TableHead>
                <TableHead>创建 / 发布时间</TableHead>
                <TableHead className='w-44 text-end'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {versionsQuery.isLoading ? (
                Array.from({ length: 4 }).map((_, index) => (
                  <TableRow key={index}>
                    <TableCell colSpan={6}>
                      <Skeleton className='h-8 w-full' />
                    </TableCell>
                  </TableRow>
                ))
              ) : versions.length ? (
                versions.map((version) => {
                  const isCurrent = version.id === currentVersionId
                  return (
                    <TableRow key={version.id}>
                      <TableCell>
                        <div className='flex items-center gap-2'>
                          <History className='size-4 text-muted-foreground' />
                          <span className='font-medium'>
                            v{version.version}
                          </span>
                          {isCurrent && <Badge>使用中</Badge>}
                        </div>
                      </TableCell>
                      <TableCell className='font-mono text-xs'>
                        {version.model_name}
                      </TableCell>
                      <TableCell>{version.temperature}</TableCell>
                      <TableCell>
                        {version.has_api_key ? '已配置' : '未配置'}
                      </TableCell>
                      <TableCell className='text-xs text-muted-foreground'>
                        <div>
                          创建{' '}
                          {new Date(version.created_at).toLocaleString('zh-CN')}
                        </div>
                        {version.published_at && (
                          <div>
                            发布{' '}
                            {new Date(version.published_at).toLocaleString(
                              'zh-CN'
                            )}
                          </div>
                        )}
                      </TableCell>
                      <TableCell className='text-end'>
                        <div className='flex justify-end gap-1'>
                          <Button
                            size='sm'
                            variant='outline'
                            disabled={isCurrent || publishMutation.isPending}
                            onClick={() => publishMutation.mutate(version.id)}
                          >
                            <Rocket className='me-2 size-4' />
                            发布
                          </Button>
                          <Button
                            size='sm'
                            variant='outline'
                            disabled={isCurrent || rollbackMutation.isPending}
                            onClick={() => rollbackMutation.mutate(version.id)}
                          >
                            <RotateCcw className='me-2 size-4' />
                            回滚
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })
              ) : (
                <TableRow>
                  <TableCell colSpan={6} className='h-24 text-center'>
                    暂无版本
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}
