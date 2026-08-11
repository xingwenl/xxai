import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Boxes, Plus, RefreshCw, Server } from 'lucide-react'
import { toast } from 'sonner'
import {
  createAgent,
  listAgents,
  updateAgent,
  type Agent,
  type AgentInput,
} from '@/api/agent'
import { listPlatforms } from '@/api/platform'
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
import { agentSchema, type AgentForm } from './agent-form-schema'

export function AgentsPage() {
  const queryClient = useQueryClient()
  const [platformId, setPlatformId] = useState<number>()
  const [editing, setEditing] = useState<Agent | null | undefined>()
  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState('all')
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
      setEditing(undefined)
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
  // 名称/Slug 搜索与启用状态筛选在客户端完成，分页仍由后端按列表接口返回。
  const filteredAgents = (agentsQuery.data?.items ?? []).filter((agent) => {
    const matchesKeyword =
      !keyword || agent.name.includes(keyword) || agent.slug.includes(keyword)
    const matchesStatus =
      status === 'all' ||
      (status === 'active' && agent.is_active) ||
      (status === 'inactive' && !agent.is_active)
    return matchesKeyword && matchesStatus
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
            <Input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder='搜索名称或标识'
              className='w-56'
            />
            <Select value={status} onValueChange={setStatus}>
              <SelectTrigger className='w-32'>
                <SelectValue placeholder='全部状态' />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value='all'>全部状态</SelectItem>
                <SelectItem value='active'>启用</SelectItem>
                <SelectItem value='inactive'>停用</SelectItem>
              </SelectContent>
            </Select>
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
              onClick={() => setEditing(null)}
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
              ) : filteredAgents.length ? (
                filteredAgents.map((agent) => (
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
                      <Button size='sm' variant='outline' asChild>
                        <Link
                          to='/ai/bots/$agentId'
                          params={{ agentId: String(agent.id) }}
                          search={{ platform: activePlatformId }}
                        >
                          详情
                        </Link>
                      </Button>
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
        agent={editing ?? null}
        open={editing !== undefined}
        onOpenChange={(open) => !open && setEditing(undefined)}
        isSaving={saveMutation.isPending}
        onSubmit={(values) => saveMutation.mutate(values)}
      />
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
