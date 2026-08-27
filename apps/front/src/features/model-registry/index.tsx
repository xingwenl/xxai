import { useState } from 'react'
import { AxiosError } from 'axios'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Edit, Plus, RefreshCw, Server, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import {
  createPlatformModel,
  deletePlatformModel,
  listPlatformModels,
  MODEL_TYPES,
  type ModelType,
  type PlatformModel,
  type PlatformModelInput,
  updatePlatformModel,
} from '@/api/model-registry'
import { listPlatforms } from '@/api/platform'
import { handleServerError } from '@/lib/handle-server-error'
import { formatDateTime } from '@/lib/time'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { ThemeSwitch } from '@/components/theme-switch'

const MODEL_TYPE_LABELS: Record<ModelType, string> = {
  chat: '对话',
  image_generate: '生图',
  image_read: '读图',
  embedding: '向量化',
}

type ModelForm = {
  id?: number
  name: string
  model_type: ModelType
  model_name: string
  base_url: string
  api_key: string
  capabilities: string
  options: string
  is_active: boolean
}

const emptyForm: ModelForm = {
  name: '',
  model_type: 'image_generate',
  model_name: '',
  base_url: '',
  api_key: '',
  capabilities: '',
  options: '{}',
  is_active: true,
}

function defaultCapabilities(modelType: ModelType) {
  return modelType === 'image_generate' ? '{"output": "image"}' : '{}'
}

function parseJsonField(value: string, label: string): Record<string, unknown> {
  const trimmed = value.trim()
  if (!trimmed) return {}
  try {
    const parsed = JSON.parse(trimmed)
    if (
      typeof parsed !== 'object' ||
      parsed === null ||
      Array.isArray(parsed)
    ) {
      throw new Error('not an object')
    }
    return parsed
  } catch {
    toast.error(`${label}格式不正确，请输入合法 JSON 对象`)
    throw new Error(`${label} JSON 解析失败`)
  }
}

export function ModelRegistryPage() {
  const queryClient = useQueryClient()
  const [platformId, setPlatformId] = useState<number>()
  const [modelType, setModelType] = useState<ModelType | ''>('')
  const [pageNo, setPageNo] = useState(1)
  const [editing, setEditing] = useState<ModelForm | null | 'create'>(null)
  const [deleting, setDeleting] = useState<PlatformModel | null>(null)
  const platformsQuery = useQuery({
    queryKey: ['platforms'],
    queryFn: listPlatforms,
  })
  const activePlatformId = platformId ?? platformsQuery.data?.[0]?.id
  const modelsQuery = useQuery({
    queryKey: ['platform-models', activePlatformId, modelType, pageNo],
    queryFn: () =>
      listPlatformModels(activePlatformId!, {
        page_no: pageNo,
        page_size: 20,
        model_type: modelType,
      }),
    enabled: activePlatformId != null,
  })
  const invalidateModels = () =>
    queryClient.invalidateQueries({
      queryKey: ['platform-models', activePlatformId],
    })
  const saveMutation = useMutation({
    mutationFn: (form: ModelForm) => {
      if (!activePlatformId) throw new Error('请选择平台')
      const capabilities = parseJsonField(form.capabilities, '能力矩阵')
      const options = parseJsonField(form.options, '模型参数')
      const baseInput: PlatformModelInput = {
        name: form.name.trim(),
        model_type: form.model_type,
        model_name: form.model_name.trim(),
        base_url: form.base_url.trim() || undefined,
        capabilities,
        options,
        is_active: form.is_active,
      }
      const apiKey = form.api_key.trim()
      if (form.id) {
        return updatePlatformModel(activePlatformId, form.id, {
          ...baseInput,
          ...(apiKey ? { api_key: apiKey } : {}),
        })
      }
      return createPlatformModel(activePlatformId, {
        ...baseInput,
        ...(apiKey ? { api_key: apiKey } : {}),
      })
    },
    onSuccess: async (_, form) => {
      toast.success(form.id ? '模型已更新' : '模型已创建')
      setEditing(null)
      await invalidateModels()
    },
    onError: (error) => {
      if (error instanceof Error && !(error instanceof AxiosError)) return
      handleServerError(error)
    },
  })
  const toggleMutation = useMutation({
    mutationFn: ({
      model,
      is_active,
    }: {
      model: PlatformModel
      is_active: boolean
    }) => updatePlatformModel(activePlatformId!, model.id, { is_active }),
    onSuccess: async () => {
      toast.success('模型状态已更新')
      await invalidateModels()
    },
    onError: (error) => handleServerError(error),
  })
  const deleteMutation = useMutation({
    mutationFn: (model: PlatformModel) =>
      deletePlatformModel(activePlatformId!, model.id),
    onSuccess: async () => {
      toast.success('模型已删除')
      setDeleting(null)
      await invalidateModels()
    },
    onError: (error) => {
      const message =
        error instanceof AxiosError ? error.response?.data?.message : undefined
      if (message === 'model_in_use') {
        toast.error('该模型已被 Agent 绑定，请先解绑后再删除')
      } else {
        handleServerError(error)
      }
      setDeleting(null)
    },
  })
  const selectedPlatform = platformsQuery.data?.find(
    (item) => item.id === activePlatformId
  )
  const page = modelsQuery.data
  const workingForm = editing === 'create' ? { ...emptyForm } : editing

  return (
    <>
      <Header fixed>
        <div />
        <div className='ms-auto flex items-center space-x-4'>
          <ThemeSwitch />
          <ConfigDrawer />
          <ProfileDropdown />
        </div>
      </Header>
      <Main className='flex flex-1 flex-col gap-4 sm:gap-6'>
        <div className='flex flex-wrap items-end justify-between gap-3'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>模型管理</h2>
            <p className='text-muted-foreground'>
              维护平台模型注册表，供 Agent 按能力角色绑定
            </p>
          </div>
          <div className='flex flex-wrap items-center gap-3'>
            <Select
              value={activePlatformId != null ? String(activePlatformId) : ''}
              onValueChange={(value) => {
                setPlatformId(Number(value))
                setPageNo(1)
              }}
            >
              <SelectTrigger className='w-44'>
                <SelectValue placeholder='选择平台' />
              </SelectTrigger>
              <SelectContent>
                {(platformsQuery.data ?? []).map((platform) => (
                  <SelectItem key={platform.id} value={String(platform.id)}>
                    {platform.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant='outline'
              size='icon'
              onClick={() => modelsQuery.refetch()}
              disabled={modelsQuery.isFetching}
              aria-label='刷新'
            >
              <RefreshCw
                className={`size-4 ${modelsQuery.isFetching ? 'animate-spin' : ''}`}
              />
            </Button>
            <Button onClick={() => setEditing('create')}>
              <Plus className='size-4' />
              新建模型
            </Button>
          </div>
        </div>
        <div className='flex flex-wrap items-center justify-between gap-3'>
          <Select
            value={modelType || 'all'}
            onValueChange={(value) => {
              setModelType(value === 'all' ? '' : (value as ModelType))
              setPageNo(1)
            }}
          >
            <SelectTrigger className='w-40'>
              <SelectValue placeholder='全部类型' />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value='all'>全部类型</SelectItem>
              {MODEL_TYPES.map((type) => (
                <SelectItem key={type} value={type}>
                  {MODEL_TYPE_LABELS[type]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className='text-sm text-muted-foreground'>
            当前平台：{selectedPlatform?.name ?? '未选择平台'}
          </p>
        </div>
        {modelsQuery.isLoading ? (
          <div className='space-y-2'>
            <Skeleton className='h-12 w-full' />
            <Skeleton className='h-12 w-full' />
            <Skeleton className='h-12 w-full' />
          </div>
        ) : modelsQuery.isError ? (
          <div className='flex min-h-40 flex-col items-center justify-center gap-3 rounded-md border border-dashed p-6 text-center'>
            <Server className='size-8 text-muted-foreground' />
            <p className='text-sm text-muted-foreground'>模型列表加载失败</p>
            <Button
              size='sm'
              variant='outline'
              onClick={() => modelsQuery.refetch()}
            >
              重试
            </Button>
          </div>
        ) : (
          <>
            <div className='rounded-md border'>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>名称</TableHead>
                    <TableHead>类型</TableHead>
                    <TableHead>上游模型</TableHead>
                    <TableHead>服务地址</TableHead>
                    <TableHead>密钥</TableHead>
                    <TableHead>更新时间</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead className='text-right'>操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(page?.items ?? []).length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={8} className='h-24 text-center'>
                        暂无模型，点击右上角「新建模型」创建
                      </TableCell>
                    </TableRow>
                  ) : (
                    (page?.items ?? []).map((model) => (
                      <TableRow key={model.id}>
                        <TableCell className='font-medium'>
                          {model.name}
                        </TableCell>
                        <TableCell>
                          <Badge variant='outline'>
                            {MODEL_TYPE_LABELS[model.model_type]}
                          </Badge>
                        </TableCell>
                        <TableCell className='font-mono text-sm'>
                          {model.model_name}
                        </TableCell>
                        <TableCell
                          className='max-w-56 truncate text-sm text-muted-foreground'
                          title={model.base_url ?? ''}
                        >
                          {model.base_url || '-'}
                        </TableCell>
                        <TableCell>
                          {model.has_api_key ? (
                            <Badge>已配置</Badge>
                          ) : (
                            <Badge variant='secondary'>未配置</Badge>
                          )}
                        </TableCell>
                        <TableCell className='text-sm text-muted-foreground'>
                          {formatDateTime(model.updated_at)}
                        </TableCell>
                        <TableCell>
                          <div className='flex items-center gap-2'>
                            <Switch
                              checked={model.is_active}
                              onCheckedChange={(checked) =>
                                toggleMutation.mutate({
                                  model,
                                  is_active: checked,
                                })
                              }
                            />
                            <span className='text-sm text-muted-foreground'>
                              {model.is_active ? '启用' : '停用'}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell className='text-right'>
                          <div className='flex justify-end gap-1'>
                            <Button
                              variant='ghost'
                              size='icon'
                              aria-label='编辑'
                              onClick={() =>
                                setEditing({
                                  id: model.id,
                                  name: model.name,
                                  model_type: model.model_type,
                                  model_name: model.model_name,
                                  base_url: model.base_url ?? '',
                                  api_key: '',
                                  capabilities: model.capabilities
                                    ? JSON.stringify(
                                        model.capabilities,
                                        null,
                                        2
                                      )
                                    : '',
                                  options: JSON.stringify(
                                    model.options,
                                    null,
                                    2
                                  ),
                                  is_active: model.is_active,
                                })
                              }
                            >
                              <Edit className='size-4' />
                            </Button>
                            <Button
                              variant='ghost'
                              size='icon'
                              aria-label='删除'
                              className='text-destructive hover:text-destructive'
                              onClick={() => setDeleting(model)}
                            >
                              <Trash2 className='size-4' />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
            {page != null && page.total > 0 && (
              <div className='flex flex-wrap items-center justify-between gap-3'>
                <p className='text-sm text-muted-foreground'>
                  共 {page.total} 条，第 {page.page_no} / {page.pages} 页
                </p>
                <div className='flex items-center gap-2'>
                  <Button
                    variant='outline'
                    size='sm'
                    disabled={page.page_no <= 1}
                    onClick={() => setPageNo((value) => Math.max(1, value - 1))}
                  >
                    上一页
                  </Button>
                  <Button
                    variant='outline'
                    size='sm'
                    disabled={page.page_no >= page.pages}
                    onClick={() =>
                      setPageNo((value) => Math.min(page.pages, value + 1))
                    }
                  >
                    下一页
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </Main>

      <Dialog
        open={editing != null}
        onOpenChange={(open) => {
          if (!open) setEditing(null)
        }}
      >
        <DialogContent className='sm:max-w-lg'>
          <DialogHeader>
            <DialogTitle>
              {editing === 'create' ? '新建模型' : '编辑模型'}
            </DialogTitle>
            <DialogDescription>
              API Key 仅写入不返回，编辑时留空表示保留原密钥
            </DialogDescription>
          </DialogHeader>
          {workingForm && (
            <ModelFormFields
              form={workingForm}
              onChange={(next) => setEditing({ ...workingForm, ...next })}
              disabled={saveMutation.isPending}
            />
          )}
          <DialogFooter>
            <Button
              variant='outline'
              onClick={() => setEditing(null)}
              disabled={saveMutation.isPending}
            >
              取消
            </Button>
            <Button
              onClick={() => {
                if (workingForm) saveMutation.mutate(workingForm)
              }}
              disabled={saveMutation.isPending}
            >
              {saveMutation.isPending ? '保存中…' : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={deleting != null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除模型</AlertDialogTitle>
            <AlertDialogDescription>
              确定删除模型「{deleting?.name}」吗？若已被 Agent 绑定将无法删除。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteMutation.isPending}>
              取消
            </AlertDialogCancel>
            <AlertDialogAction
              className='bg-destructive text-white hover:bg-destructive/90'
              disabled={deleteMutation.isPending}
              onClick={(event) => {
                event.preventDefault()
                if (deleting) deleteMutation.mutate(deleting)
              }}
            >
              {deleteMutation.isPending ? '删除中…' : '删除'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function ModelFormFields({
  form,
  onChange,
  disabled,
}: {
  form: ModelForm
  onChange: (next: Partial<ModelForm>) => void
  disabled: boolean
}) {
  const isEdit = form.id != null
  return (
    <div className='grid gap-4 py-2'>
      <div className='grid grid-cols-2 gap-4'>
        <div className='grid gap-2'>
          <Label htmlFor='model-name'>名称</Label>
          <Input
            id='model-name'
            value={form.name}
            placeholder='如：OpenAI 生图'
            disabled={disabled}
            onChange={(event) => onChange({ name: event.target.value })}
          />
        </div>
        <div className='grid gap-2'>
          <Label htmlFor='model-type'>类型</Label>
          <Select
            value={form.model_type}
            onValueChange={(value) =>
              onChange({
                model_type: value as ModelType,
                ...(isEdit
                  ? {}
                  : { capabilities: defaultCapabilities(value as ModelType) }),
              })
            }
            disabled={disabled}
          >
            <SelectTrigger id='model-type'>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {MODEL_TYPES.map((type) => (
                <SelectItem key={type} value={type}>
                  {MODEL_TYPE_LABELS[type]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className='grid gap-2'>
        <Label htmlFor='model-name-upstream'>上游模型名</Label>
        <Input
          id='model-name-upstream'
          value={form.model_name}
          placeholder='如：gpt-image-1'
          disabled={disabled}
          onChange={(event) => onChange({ model_name: event.target.value })}
        />
      </div>
      <div className='grid gap-2'>
        <Label htmlFor='model-base-url'>服务地址（可选）</Label>
        <Input
          id='model-base-url'
          value={form.base_url}
          placeholder='留空使用官方默认地址，一般需以 /v1 结尾'
          disabled={disabled}
          onChange={(event) => onChange({ base_url: event.target.value })}
        />
      </div>
      <div className='grid gap-2'>
        <Label htmlFor='model-api-key'>
          API Key{isEdit ? '（留空保留原值）' : ''}
        </Label>
        <Input
          id='model-api-key'
          type='password'
          value={form.api_key}
          placeholder={isEdit ? '留空则不修改' : '可选'}
          autoComplete='new-password'
          disabled={disabled}
          onChange={(event) => onChange({ api_key: event.target.value })}
        />
      </div>
      <div className='grid gap-2'>
        <Label htmlFor='model-capabilities'>能力矩阵（JSON）</Label>
        <Textarea
          id='model-capabilities'
          value={form.capabilities}
          rows={3}
          placeholder='{"image": true, "output": "image"}'
          disabled={disabled}
          onChange={(event) => onChange({ capabilities: event.target.value })}
        />
      </div>
      <div className='grid gap-2'>
        <Label htmlFor='model-options'>模型参数（JSON）</Label>
        <Textarea
          id='model-options'
          value={form.options}
          rows={2}
          placeholder='{}'
          disabled={disabled}
          onChange={(event) => onChange({ options: event.target.value })}
        />
      </div>
      <div className='flex items-center justify-between rounded-md border p-3'>
        <div>
          <p className='text-sm font-medium'>启用</p>
          <p className='text-xs text-muted-foreground'>
            停用后 Agent 无法绑定该模型
          </p>
        </div>
        <Switch
          checked={form.is_active}
          disabled={disabled}
          onCheckedChange={(checked) => onChange({ is_active: checked })}
        />
      </div>
    </div>
  )
}
