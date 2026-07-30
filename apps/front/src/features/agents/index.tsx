import { useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Edit, Plus, RefreshCw, Server, Trash2, Boxes } from 'lucide-react'
import { toast } from 'sonner'
import {
  createAgent,
  createAgentVersion,
  deleteAgent,
  listAgentVersions,
  listAgents,
  publishAgentVersion,
  rollbackAgentVersion,
  updateAgent,
  type Agent,
  type AgentInput,
  type AgentVersionInput,
} from '@/api/agent'
import { listPlatforms } from '@/api/platform'
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
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
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

const agentSchema = z.object({
  name: z.string().min(1, '请输入名称').max(120),
  slug: z
    .string()
    .min(2, '标识至少 2 个字符')
    .regex(/^[a-z0-9][a-z0-9_-]*$/, '只允许小写字母、数字、下划线和短横线'),
  description: z.string().max(500).optional(),
  is_active: z.boolean(),
})
const versionSchema = z.object({
  system_prompt: z.string().min(1, '请输入系统提示词'),
  model_name: z.string().min(1, '请输入模型名称').max(120),
  model_base_url: z.string().url('请输入有效 URL').optional().or(z.literal('')),
  api_key: z.string().optional(),
  temperature: z.coerce.number().min(0).max(2),
})
type AgentForm = z.infer<typeof agentSchema>
type VersionForm = z.infer<typeof versionSchema>

export function AgentsPage() {
  const queryClient = useQueryClient()
  const [platformId, setPlatformId] = useState<number>()
  const [editing, setEditing] = useState<Agent | null>(null)
  const [deleting, setDeleting] = useState<Agent | null>(null)
  const [versionsFor, setVersionsFor] = useState<Agent | null>(null)
  const [versionDialog, setVersionDialog] = useState(false)
  const platformsQuery = useQuery({
    queryKey: ['platforms'],
    queryFn: listPlatforms,
  })
  const activePlatformId = platformId ?? platformsQuery.data?.[0]?.id
  const agentsQuery = useQuery({
    queryKey: ['agents', activePlatformId],
    queryFn: () => listAgents(activePlatformId!),
    enabled: activePlatformId != null,
  })
  const invalidateAgents = () =>
    queryClient.invalidateQueries({ queryKey: ['agents', activePlatformId] })
  const saveMutation = useMutation({
    mutationFn: (values: AgentForm) => {
      if (!activePlatformId) throw new Error('请选择平台')
      const input: AgentInput = {
        name: values.name,
        slug: values.slug,
        description: values.description,
      }
      return editing
        ? updateAgent(activePlatformId, editing.id, {
            ...input,
            is_active: values.is_active,
          })
        : createAgent(activePlatformId, input)
    },
    onSuccess: async () => {
      toast.success(editing ? '智能体已更新' : '智能体已创建')
      setEditing(null)
      await invalidateAgents()
    },
  })
  const statusMutation = useMutation({
    mutationFn: ({ agent, is_active }: { agent: Agent; is_active: boolean }) =>
      updateAgent(activePlatformId!, agent.id, {
        name: agent.name,
        slug: agent.slug,
        description: agent.description ?? undefined,
        is_active,
      }),
    onSuccess: async () => {
      toast.success('状态已更新')
      await invalidateAgents()
    },
  })
  const deleteMutation = useMutation({
    mutationFn: (agent: Agent) => deleteAgent(activePlatformId!, agent.id),
    onSuccess: async () => {
      toast.success('智能体及其版本已删除')
      setDeleting(null)
      await invalidateAgents()
    },
  })
  const selectedPlatform = platformsQuery.data?.find(
    (item) => item.id === activePlatformId
  )
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
            <h2 className='text-2xl font-bold tracking-tight'>智能体管理</h2>
            <p className='text-muted-foreground'>
              管理平台内的智能体和模型版本。
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <Select
              value={activePlatformId?.toString()}
              onValueChange={(value) => setPlatformId(Number(value))}
            >
              <SelectTrigger className='w-52'>
                <SelectValue placeholder='选择平台' />
              </SelectTrigger>
              <SelectContent>
                {(platformsQuery.data ?? []).map((platform) => (
                  <SelectItem key={platform.id} value={platform.id.toString()}>
                    {platform.name} ({platform.code})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant='outline'
              size='sm'
              onClick={() => agentsQuery.refetch()}
              disabled={!activePlatformId || agentsQuery.isFetching}
            >
              <RefreshCw className='me-2 size-4' />
              刷新
            </Button>
            <Button
              size='sm'
              onClick={() => setEditing({} as Agent)}
              disabled={!activePlatformId}
            >
              <Plus className='me-2 size-4' />
              新建智能体
            </Button>
          </div>
        </div>
        <div className='rounded-md border bg-muted/30 px-4 py-3 text-sm'>
          <Server className='me-2 inline size-4' />
          当前平台：{selectedPlatform?.name ?? '未选择平台'}
        </div>
        <div className='overflow-hidden rounded-md border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>智能体</TableHead>
                <TableHead>描述</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className='w-44 text-end'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {agentsQuery.isLoading ? (
                Array.from({ length: 5 }).map((_, index) => (
                  <TableRow key={index}>
                    <TableCell colSpan={4}>
                      <Skeleton className='h-8 w-full' />
                    </TableCell>
                  </TableRow>
                ))
              ) : agentsQuery.data?.items.length ? (
                agentsQuery.data.items.map((agent) => (
                  <TableRow key={agent.id}>
                    <TableCell>
                      <div className='flex items-center gap-3'>
                        <div className='flex size-9 items-center justify-center rounded-md bg-muted'>
                          <Boxes className='size-4 text-muted-foreground' />
                        </div>
                        <div>
                          <div className='font-medium'>
                            {agent.name}{' '}
                            {agent.is_default && (
                              <Badge variant='outline'>默认</Badge>
                            )}
                          </div>
                          <div className='text-xs text-muted-foreground'>
                            {agent.slug} · ID {agent.id}
                          </div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className='max-w-md truncate'>
                      {agent.description || '-'}
                    </TableCell>
                    <TableCell>
                      <div className='flex items-center gap-2'>
                        <Switch
                          checked={agent.is_active}
                          disabled={statusMutation.isPending}
                          onCheckedChange={(is_active) =>
                            statusMutation.mutate({ agent, is_active })
                          }
                        />
                        <Badge
                          variant={agent.is_active ? 'default' : 'secondary'}
                        >
                          {agent.is_active ? '启用' : '停用'}
                        </Badge>
                      </div>
                    </TableCell>
                    <TableCell className='text-end'>
                      <div className='flex justify-end gap-1'>
                        <Button
                          size='icon'
                          variant='ghost'
                          onClick={() => setVersionsFor(agent)}
                        >
                          <span className='sr-only'>版本</span>
                          <RefreshCw className='size-4' />
                        </Button>
                        <Button
                          size='icon'
                          variant='ghost'
                          onClick={() => setEditing(agent)}
                        >
                          <Edit className='size-4' />
                          <span className='sr-only'>编辑</span>
                        </Button>
                        <Button
                          size='icon'
                          variant='ghost'
                          className='text-destructive hover:text-destructive'
                          onClick={() => setDeleting(agent)}
                        >
                          <Trash2 className='size-4' />
                          <span className='sr-only'>删除</span>
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={4} className='h-24 text-center'>
                    暂无智能体
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
        <div className='text-sm text-muted-foreground'>
          共 {agentsQuery.data?.total ?? 0} 个智能体
        </div>
      </Main>
      <AgentDialog
        agent={editing && editing.id ? editing : null}
        open={!!editing}
        onOpenChange={(open) => !open && setEditing(null)}
        isSaving={saveMutation.isPending}
        onSubmit={(values) => saveMutation.mutate(values)}
      />
      {activePlatformId && versionsFor && (
        <VersionsDialog
          platformId={activePlatformId}
          agent={versionsFor}
          open
          onOpenChange={(open) => !open && setVersionsFor(null)}
          onCreate={() => setVersionDialog(true)}
        />
      )}
      {activePlatformId && versionsFor && (
        <VersionFormDialog
          platformId={activePlatformId}
          agent={versionsFor}
          open={versionDialog}
          onOpenChange={setVersionDialog}
          onCreated={() => {
            setVersionDialog(false)
            queryClient.invalidateQueries({
              queryKey: ['agent-versions', activePlatformId, versionsFor.id],
            })
          }}
        />
      )}
      <AlertDialog
        open={!!deleting}
        onOpenChange={(open) => !open && setDeleting(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>硬删除智能体</AlertDialogTitle>
            <AlertDialogDescription>
              确认删除 {deleting?.name}
              ？该智能体及其所有版本将永久删除，无法恢复。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleting && deleteMutation.mutate(deleting)}
              className='text-destructive-foreground bg-destructive hover:bg-destructive/90'
            >
              永久删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function AgentDialog({
  agent,
  open,
  onOpenChange,
  isSaving,
  onSubmit,
}: {
  agent: Agent | null
  open: boolean
  onOpenChange: (open: boolean) => void
  isSaving: boolean
  onSubmit: (values: AgentForm) => void
}) {
  const form = useForm<AgentForm>({
    resolver: zodResolver(agentSchema),
    values: {
      name: agent?.name ?? '',
      slug: agent?.slug ?? '',
      description: agent?.description ?? '',
      is_active: agent?.is_active ?? true,
    },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{agent ? '编辑智能体' : '新建智能体'}</DialogTitle>
          <DialogDescription>
            slug 创建后建议保持稳定，供 API 和嵌入式调用识别。
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            id='agent-form'
            onSubmit={form.handleSubmit(onSubmit)}
            className='grid gap-4'
          >
            <FormField
              control={form.control}
              name='name'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>名称</FormLabel>
                  <FormControl>
                    <Input placeholder='客服助手' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='slug'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Slug</FormLabel>
                  <FormControl>
                    <Input
                      disabled={!!agent}
                      placeholder='support'
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='description'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>描述</FormLabel>
                  <FormControl>
                    <Textarea rows={3} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            {agent && (
              <FormField
                control={form.control}
                name='is_active'
                render={({ field }) => (
                  <FormItem className='flex items-center justify-between rounded-md border p-3'>
                    <FormLabel>启用智能体</FormLabel>
                    <FormControl>
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                  </FormItem>
                )}
              />
            )}
          </form>
        </Form>
        <DialogFooter>
          <Button type='submit' form='agent-form' disabled={isSaving}>
            {isSaving ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function VersionsDialog({
  platformId,
  agent,
  open,
  onOpenChange,
  onCreate,
}: {
  platformId: number
  agent: Agent
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreate: () => void
}) {
  const queryClient = useQueryClient()
  const versionsQuery = useQuery({
    queryKey: ['agent-versions', platformId, agent.id],
    queryFn: () => listAgentVersions(platformId, agent.id),
    enabled: open,
  })
  const publishMutation = useMutation({
    mutationFn: (versionId: number) =>
      publishAgentVersion(platformId, agent.id, versionId),
    onSuccess: async () => {
      toast.success('版本已发布')
      await queryClient.invalidateQueries({
        queryKey: ['agent-versions', platformId, agent.id],
      })
    },
  })
  const rollbackMutation = useMutation({
    mutationFn: (versionId: number) =>
      rollbackAgentVersion(platformId, agent.id, versionId),
    onSuccess: async () => {
      toast.success('版本已回滚')
      await queryClient.invalidateQueries({
        queryKey: ['agent-versions', platformId, agent.id],
      })
    },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-w-3xl'>
        <DialogHeader>
          <DialogTitle>{agent.name} · 版本管理</DialogTitle>
          <DialogDescription>
            API Key 仅在创建版本时提交，后端不会返回明文。
          </DialogDescription>
        </DialogHeader>
        <div className='flex justify-end'>
          <Button size='sm' onClick={onCreate}>
            <Plus className='me-2 size-4' />
            新建版本
          </Button>
        </div>
        <div className='max-h-[50vh] overflow-auto rounded-md border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>版本</TableHead>
                <TableHead>模型</TableHead>
                <TableHead>温度</TableHead>
                <TableHead>API Key</TableHead>
                <TableHead>发布时间</TableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {versionsQuery.isLoading ? (
                <TableRow>
                  <TableCell colSpan={6}>
                    <Skeleton className='h-8 w-full' />
                  </TableCell>
                </TableRow>
              ) : versionsQuery.data?.length ? (
                versionsQuery.data.map((version) => (
                  <TableRow key={version.id}>
                    <TableCell>v{version.version}</TableCell>
                    <TableCell>{version.model_name}</TableCell>
                    <TableCell>{version.temperature}</TableCell>
                    <TableCell>
                      {version.has_api_key ? '已配置' : '未配置'}
                    </TableCell>
                    <TableCell>
                      {version.published_at
                        ? new Date(version.published_at).toLocaleString()
                        : '未发布'}
                    </TableCell>
                    <TableCell>
                      <div className='flex gap-1'>
                        {!version.published_at && (
                          <Button
                            size='sm'
                            variant='outline'
                            onClick={() => publishMutation.mutate(version.id)}
                          >
                            发布
                          </Button>
                        )}
                        {version.published_at && (
                          <Button
                            size='sm'
                            variant='outline'
                            onClick={() => rollbackMutation.mutate(version.id)}
                          >
                            回滚
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={6} className='h-20 text-center'>
                    暂无版本
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function VersionFormDialog({
  platformId,
  agent,
  open,
  onOpenChange,
  onCreated,
}: {
  platformId: number
  agent: Agent
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: () => void
}) {
  const form = useForm<VersionForm>({
    resolver: zodResolver(versionSchema),
    defaultValues: {
      system_prompt: '',
      model_name: 'gpt-4o-mini',
      model_base_url: '',
      api_key: '',
      temperature: 0.2,
    },
  })
  const mutation = useMutation({
    mutationFn: (values: VersionForm) => {
      const input: AgentVersionInput = {
        ...values,
        api_key: values.api_key || undefined,
        model_base_url: values.model_base_url || undefined,
        model_options: {},
      }
      return createAgentVersion(platformId, agent.id, input)
    },
    onSuccess: () => {
      toast.success('版本已创建')
      form.reset()
      onCreated()
    },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-w-2xl'>
        <DialogHeader>
          <DialogTitle>为 {agent.name} 创建版本</DialogTitle>
        </DialogHeader>
        <Form {...form}>
          <form
            id='agent-version-form'
            onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
            className='grid gap-4'
          >
            <FormField
              control={form.control}
              name='model_name'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>模型名称</FormLabel>
                  <FormControl>
                    <Input {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='model_base_url'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>模型地址</FormLabel>
                  <FormControl>
                    <Input
                      placeholder='可选，例如 https://api.openai.com/v1'
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='api_key'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>API Key</FormLabel>
                  <FormControl>
                    <Input
                      type='password'
                      placeholder='仅本次提交'
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='temperature'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Temperature</FormLabel>
                  <FormControl>
                    <Input
                      type='number'
                      min='0'
                      max='2'
                      step='0.1'
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='system_prompt'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>系统提示词</FormLabel>
                  <FormControl>
                    <Textarea rows={6} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </form>
        </Form>
        <DialogFooter>
          <Button
            type='submit'
            form='agent-version-form'
            disabled={mutation.isPending}
          >
            {mutation.isPending ? '保存中...' : '创建版本'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
