import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Save } from 'lucide-react'
import { toast } from 'sonner'
import {
  BINDING_ROLES,
  listAgentModelBindings,
  listPlatformModels,
  replaceAgentModelBindings,
  type BindingRole,
} from '@/api/model-registry'
import { handleServerError } from '@/lib/handle-server-error'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'

const ROLE_META: Record<BindingRole, { label: string; description: string }> = {
  chat: {
    label: '对话',
    description: '对话主链路使用的模型；未绑定时回退运行栈的全局默认模型',
  },
  image_generate: {
    label: '生图',
    description: '内置「生成图片」工具使用的模型',
  },
  image_read: {
    label: '读图',
    description: '内置「读取图片」工具使用的模型',
  },
  embedding: {
    label: '向量化',
    description: '附件知识检索 embedding 使用的模型',
  },
}

export function AgentModelBindingsTab({
  platformId,
  agentId,
}: {
  platformId?: number
  agentId: number
}) {
  const queryClient = useQueryClient()
  // null 表示跟随服务端绑定；用户修改后变为本地草稿
  const [draft, setDraft] = useState<Partial<
    Record<BindingRole, number>
  > | null>(null)
  const modelsQuery = useQuery({
    queryKey: ['platform-models', platformId],
    queryFn: () => listPlatformModels(platformId!, { page_size: 100 }),
    enabled: platformId != null,
  })
  const bindingsQuery = useQuery({
    queryKey: ['agent-model-bindings', platformId, agentId],
    queryFn: () => listAgentModelBindings(platformId!, agentId),
    enabled: platformId != null,
  })

  const boundRoles = useMemo(() => {
    const map: Partial<Record<BindingRole, number>> = {}
    for (const item of bindingsQuery.data?.items ?? []) {
      map[item.role] = item.model_id
    }
    return map
  }, [bindingsQuery.data])

  const saveMutation = useMutation({
    mutationFn: () => {
      if (platformId == null) throw new Error('请选择平台')
      const bindings = Object.entries(selections)
        .filter((entry): entry is [BindingRole, number] => entry[1] != null)
        .map(([role, modelId]) => ({ role, model_id: modelId }))
      return replaceAgentModelBindings(platformId, agentId, bindings)
    },
    onSuccess: async () => {
      toast.success('模型绑定已保存')
      await queryClient.invalidateQueries({
        queryKey: ['agent-model-bindings', platformId, agentId],
      })
    },
    onError: (error) => handleServerError(error),
  })

  const selections = draft ?? boundRoles
  const dirty =
    draft != null && JSON.stringify(draft) !== JSON.stringify(boundRoles)
  const allModels = modelsQuery.data?.items ?? []
  const boundInactive = new Set(
    (bindingsQuery.data?.items ?? [])
      .filter((item) => !item.is_active)
      .map((item) => item.model_id)
  )

  return (
    <Card>
      <CardHeader className='flex-row items-start justify-between space-y-0'>
        <div>
          <CardTitle>模型绑定</CardTitle>
          <CardDescription>
            按能力角色绑定注册表模型；未绑定的角色自动回退全局配置
          </CardDescription>
        </div>
        <div className='flex items-center gap-2'>
          <Button
            variant='outline'
            size='sm'
            onClick={() => {
              setDraft(null)
              bindingsQuery.refetch()
            }}
            disabled={bindingsQuery.isFetching}
          >
            <RefreshCw
              className={`size-4 ${bindingsQuery.isFetching ? 'animate-spin' : ''}`}
            />
            重置
          </Button>
          <Button
            size='sm'
            disabled={!dirty || saveMutation.isPending}
            onClick={() => saveMutation.mutate()}
          >
            <Save className='size-4' />
            {saveMutation.isPending ? '保存中…' : '保存'}
          </Button>
        </div>
      </CardHeader>
      <CardContent className='grid gap-4'>
        {modelsQuery.isLoading || bindingsQuery.isLoading ? (
          <div className='space-y-3'>
            <Skeleton className='h-16 w-full' />
            <Skeleton className='h-16 w-full' />
            <Skeleton className='h-16 w-full' />
          </div>
        ) : (
          BINDING_ROLES.map((role) => {
            const meta = ROLE_META[role]
            const candidates = allModels.filter(
              (model) => model.model_type === role && model.is_active
            )
            const inactiveBound = allModels.filter(
              (model) =>
                model.model_type === role && boundInactive.has(model.id)
            )
            const selectedId = selections[role]
            const selectedModel = allModels.find(
              (model) => model.id === selectedId
            )
            return (
              <div
                key={role}
                className='flex flex-wrap items-center justify-between gap-3 rounded-md border p-4'
              >
                <div className='min-w-48'>
                  <div className='flex items-center gap-2'>
                    <p className='text-sm font-medium'>{meta.label}</p>
                    <Badge variant='secondary' className='font-mono'>
                      {role}
                    </Badge>
                  </div>
                  <p className='mt-1 text-xs text-muted-foreground'>
                    {meta.description}
                  </p>
                  {selectedModel && (
                    <p className='mt-1 text-xs text-muted-foreground'>
                      当前：{selectedModel.name}（{selectedModel.model_name}）
                    </p>
                  )}
                </div>
                <div className='flex items-center gap-2'>
                  {inactiveBound.length > 0 && (
                    <Badge variant='destructive'>绑定模型已停用</Badge>
                  )}
                  <Select
                    value={selectedId != null ? String(selectedId) : 'none'}
                    onValueChange={(value) =>
                      setDraft((prev) => ({
                        ...(prev ?? boundRoles),
                        [role]: value === 'none' ? undefined : Number(value),
                      }))
                    }
                  >
                    <SelectTrigger className='w-64'>
                      <SelectValue placeholder='回退全局配置（不绑定）' />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value='none'>
                        回退全局配置（不绑定）
                      </SelectItem>
                      {candidates.map((model) => (
                        <SelectItem key={model.id} value={String(model.id)}>
                          {model.name}（{model.model_name}）
                        </SelectItem>
                      ))}
                      {inactiveBound.map((model) => (
                        <SelectItem key={model.id} value={String(model.id)}>
                          {model.name}（{model.model_name}，已停用）
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            )
          })
        )}
      </CardContent>
    </Card>
  )
}
