import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Link2, RefreshCw, RotateCw, Server } from 'lucide-react'
import { toast } from 'sonner'
import { listAgents, type Agent } from '@/api/agent'
import {
  bindEmbedClientAgent,
  createEmbedClient,
  listEmbedClientAgents,
  listEmbedClients,
  rotateEmbedClientSecret,
  unbindEmbedClientAgent,
  updateEmbedClient,
  type EmbedClient,
  type EmbedClientInput,
} from '@/api/embed-clients'
import {
  bindEmbedClientHostTool,
  listEmbedClientHostTools,
  listHostTools,
  unbindEmbedClientHostTool,
  type HostToolPolicy,
} from '@/api/host-tools'
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

type ClientForm = {
  name: string
  allowed_origins: string
  token_ttl_seconds: number
  max_tokens_per_minute: string
  max_connections: string
  is_active: boolean
}

const defaultForm: ClientForm = {
  name: '',
  allowed_origins: 'https://example.com',
  token_ttl_seconds: 600,
  max_tokens_per_minute: '',
  max_connections: '',
  is_active: true,
}

export function EmbedClientsPage() {
  const queryClient = useQueryClient()
  const [platformId, setPlatformId] = useState<number>()
  const [editing, setEditing] = useState<EmbedClient | null | undefined>()
  const [bindingClient, setBindingClient] = useState<EmbedClient | null>(null)
  const [secretResult, setSecretResult] = useState<{
    title: string
    clientId: string
    secret: string
  } | null>(null)
  const platformsQuery = useQuery({
    queryKey: ['platforms'],
    queryFn: listPlatforms,
  })
  const activePlatformId = platformId ?? platformsQuery.data?.[0]?.id
  const clientsQuery = useQuery({
    queryKey: ['embed-clients', activePlatformId],
    queryFn: () => listEmbedClients(activePlatformId!),
    enabled: activePlatformId != null,
  })
  const invalidateClients = () =>
    queryClient.invalidateQueries({
      queryKey: ['embed-clients', activePlatformId],
    })
  const saveMutation = useMutation({
    mutationFn: async (form: ClientForm) => {
      if (!activePlatformId) throw new Error('请选择平台')
      const input = toClientInput(form)
      return editing
        ? updateEmbedClient(activePlatformId, editing.client_id, {
            ...input,
            is_active: form.is_active,
          })
        : createEmbedClient(activePlatformId, input)
    },
    onSuccess: async (result) => {
      if ('client_secret' in result) {
        setSecretResult({
          title: 'Embed Client 已创建',
          clientId: result.client.client_id,
          secret: result.client_secret,
        })
      }
      toast.success(editing ? 'Embed Client 已更新' : 'Embed Client 已创建')
      setEditing(undefined)
      await invalidateClients()
    },
  })
  const toggleMutation = useMutation({
    mutationFn: ({
      client,
      is_active,
    }: {
      client: EmbedClient
      is_active: boolean
    }) =>
      updateEmbedClient(activePlatformId!, client.client_id, {
        name: client.name,
        allowed_origins: client.allowed_origins,
        token_ttl_seconds: client.token_ttl_seconds,
        max_tokens_per_minute: client.max_tokens_per_minute,
        max_connections: client.max_connections,
        is_active,
      }),
    onSuccess: async () => {
      toast.success('Client 状态已更新')
      await invalidateClients()
    },
  })
  const rotateMutation = useMutation({
    mutationFn: (client: EmbedClient) =>
      rotateEmbedClientSecret(activePlatformId!, client.client_id).then(
        (result) => ({ client, secret: result.client_secret })
      ),
    onSuccess: ({ client, secret }) => {
      setSecretResult({
        title: 'Client Secret 已轮换',
        clientId: client.client_id,
        secret,
      })
      toast.success('密钥已轮换')
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
            <h2 className='text-2xl font-bold tracking-tight'>
              Embed Client 管理
            </h2>
            <p className='text-muted-foreground'>
              管理第三方页面接入凭据、Origin 白名单和可访问能力。
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
              onClick={() => clientsQuery.refetch()}
              disabled={!activePlatformId || clientsQuery.isFetching}
            >
              <RefreshCw className='size-4' />
              刷新
            </Button>
            <Button
              size='sm'
              onClick={() => setEditing(null)}
              disabled={!activePlatformId}
            >
              <KeyRound className='size-4' />
              新建 Client
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
                <TableHead>Client</TableHead>
                <TableHead>Origin</TableHead>
                <TableHead>TTL / 限额</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className='w-44 text-end'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {clientsQuery.isLoading
                ? Array.from({ length: 4 }).map((_, index) => (
                    <TableRow key={index}>
                      <TableCell colSpan={5}>
                        <Skeleton className='h-8 w-full' />
                      </TableCell>
                    </TableRow>
                  ))
                : (clientsQuery.data ?? []).map((client) => (
                    <TableRow key={client.id}>
                      <TableCell>
                        <div className='font-medium'>{client.name}</div>
                        <div className='font-mono text-xs text-muted-foreground'>
                          {client.client_id}
                        </div>
                      </TableCell>
                      <TableCell className='max-w-72'>
                        <div className='flex flex-wrap gap-1'>
                          {client.allowed_origins.map((origin) => (
                            <Badge key={origin} variant='outline'>
                              {origin}
                            </Badge>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell className='text-sm'>
                        <div>{client.token_ttl_seconds}s</div>
                        <div className='text-xs text-muted-foreground'>
                          token {client.max_tokens_per_minute ?? '默认'}/min ·
                          连接 {client.max_connections ?? '默认'}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className='flex items-center gap-2'>
                          <Switch
                            checked={client.is_active}
                            disabled={toggleMutation.isPending}
                            onCheckedChange={(is_active) =>
                              toggleMutation.mutate({ client, is_active })
                            }
                          />
                          <Badge
                            variant={client.is_active ? 'default' : 'secondary'}
                          >
                            {client.is_active ? '启用' : '停用'}
                          </Badge>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className='flex justify-end gap-1'>
                          <Button
                            size='icon'
                            variant='ghost'
                            onClick={() => setBindingClient(client)}
                          >
                            <Link2 className='size-4' />
                            <span className='sr-only'>绑定</span>
                          </Button>
                          <Button
                            size='icon'
                            variant='ghost'
                            onClick={() => setEditing(client)}
                          >
                            <KeyRound className='size-4' />
                            <span className='sr-only'>编辑</span>
                          </Button>
                          <Button
                            size='icon'
                            variant='ghost'
                            onClick={() => rotateMutation.mutate(client)}
                            disabled={rotateMutation.isPending}
                          >
                            <RotateCw className='size-4' />
                            <span className='sr-only'>轮换密钥</span>
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
              {!clientsQuery.isLoading && !clientsQuery.data?.length && (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className='h-24 text-center text-muted-foreground'
                  >
                    暂无 Embed Client
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
        <div className='text-sm text-muted-foreground'>
          共 {clientsQuery.data?.length ?? 0} 个 Client
        </div>
      </Main>
      <ClientDialog
        key={editing ? editing.client_id : 'new'}
        client={editing && editing.id ? editing : null}
        open={editing !== undefined}
        onOpenChange={(open) => !open && setEditing(undefined)}
        isSaving={saveMutation.isPending}
        onSubmit={(form) => saveMutation.mutate(form)}
      />
      {activePlatformId && bindingClient && (
        <BindingDialog
          platformId={activePlatformId}
          client={bindingClient}
          open
          onOpenChange={(open) => !open && setBindingClient(null)}
        />
      )}
      <SecretDialog
        result={secretResult}
        onClose={() => setSecretResult(null)}
      />
    </>
  )
}

function ClientDialog({
  client,
  open,
  onOpenChange,
  isSaving,
  onSubmit,
}: {
  client: EmbedClient | null
  open: boolean
  onOpenChange: (open: boolean) => void
  isSaving: boolean
  onSubmit: (form: ClientForm) => void
}) {
  const [form, setForm] = useState<ClientForm>(
    client
      ? {
          name: client.name,
          allowed_origins: client.allowed_origins.join('\n'),
          token_ttl_seconds: client.token_ttl_seconds,
          max_tokens_per_minute: client.max_tokens_per_minute?.toString() ?? '',
          max_connections: client.max_connections?.toString() ?? '',
          is_active: client.is_active,
        }
      : defaultForm
  )
  const [error, setError] = useState('')
  const update = (patch: Partial<ClientForm>) =>
    setForm((current) => ({ ...current, ...patch }))
  const submit = () => {
    try {
      toClientInput(form)
      setError('')
      onSubmit(form)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '表单无效')
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-w-2xl'>
        <DialogHeader>
          <DialogTitle>{client ? '编辑 Client' : '新建 Client'}</DialogTitle>
          <DialogDescription>
            Client secret 只会在创建或轮换成功后展示一次。
          </DialogDescription>
        </DialogHeader>
        <div className='grid gap-4'>
          <Field label='名称'>
            <Input
              value={form.name}
              onChange={(event) => update({ name: event.target.value })}
            />
          </Field>
          <Field label='Origin 白名单'>
            <Textarea
              rows={5}
              className='font-mono text-sm'
              value={form.allowed_origins}
              placeholder='https://example.com'
              onChange={(event) =>
                update({ allowed_origins: event.target.value })
              }
            />
            <p className='text-xs text-muted-foreground'>
              每行一个精确 Origin，只包含协议、域名和端口，不包含路径。
            </p>
          </Field>
          <div className='grid gap-4 sm:grid-cols-3'>
            <Field label='Token TTL 秒'>
              <Input
                type='number'
                min={300}
                max={900}
                value={form.token_ttl_seconds}
                onChange={(event) =>
                  update({ token_ttl_seconds: Number(event.target.value) })
                }
              />
            </Field>
            <Field label='Token 每分钟'>
              <Input
                value={form.max_tokens_per_minute}
                placeholder='默认'
                onChange={(event) =>
                  update({ max_tokens_per_minute: event.target.value })
                }
              />
            </Field>
            <Field label='最大连接'>
              <Input
                value={form.max_connections}
                placeholder='默认'
                onChange={(event) =>
                  update({ max_connections: event.target.value })
                }
              />
            </Field>
          </div>
          {client && (
            <div className='flex items-center justify-between rounded-md border p-3'>
              <Label>启用 Client</Label>
              <Switch
                checked={form.is_active}
                onCheckedChange={(is_active) => update({ is_active })}
              />
            </div>
          )}
          {error && <p className='text-sm text-destructive'>{error}</p>}
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={isSaving}>
            {isSaving ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function BindingDialog({
  platformId,
  client,
  open,
  onOpenChange,
}: {
  platformId: number
  client: EmbedClient
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const agentsQuery = useQuery({
    queryKey: ['agents', platformId],
    queryFn: () => listAgents(platformId),
    enabled: open,
  })
  const toolsQuery = useQuery({
    queryKey: ['host-tools', platformId],
    queryFn: () => listHostTools(platformId),
    enabled: open,
  })
  const agentBindingsQuery = useQuery({
    queryKey: ['embed-client-agents', platformId, client.client_id],
    queryFn: () => listEmbedClientAgents(platformId, client.client_id),
    enabled: open,
  })
  const toolBindingsQuery = useQuery({
    queryKey: ['embed-client-host-tools', platformId, client.client_id],
    queryFn: () => listEmbedClientHostTools(platformId, client.client_id),
    enabled: open,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ['embed-client-agents', platformId, client.client_id],
      }),
      queryClient.invalidateQueries({
        queryKey: ['embed-client-host-tools', platformId, client.client_id],
      }),
    ])
  }
  const agentMutation = useMutation({
    mutationFn: ({ agent, bound }: { agent: Agent; bound: boolean }) =>
      bound
        ? unbindEmbedClientAgent(platformId, client.client_id, agent.id)
        : bindEmbedClientAgent(platformId, client.client_id, agent.id),
    onSuccess: async () => {
      toast.success('Agent 绑定已更新')
      await invalidate()
    },
  })
  const toolMutation = useMutation({
    mutationFn: ({ tool, bound }: { tool: HostToolPolicy; bound: boolean }) =>
      bound
        ? unbindEmbedClientHostTool(platformId, client.client_id, tool.id)
        : bindEmbedClientHostTool(platformId, client.client_id, tool.id),
    onSuccess: async () => {
      toast.success('宿主工具绑定已更新')
      await invalidate()
    },
  })
  const boundAgentIds = new Set(
    (agentBindingsQuery.data ?? []).map((item) => item.agent_id)
  )
  const boundToolIds = new Set(
    (toolBindingsQuery.data ?? []).map((item) => item.tool_id)
  )
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-h-[90vh] max-w-4xl overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>{client.name} · 绑定配置</DialogTitle>
          <DialogDescription>
            token 可用能力来自 Client、Agent 和页面注册工具的交集。
          </DialogDescription>
        </DialogHeader>
        <div className='grid gap-4 md:grid-cols-2'>
          <BindingList
            title='允许访问的 Agent'
            loading={agentsQuery.isLoading || agentBindingsQuery.isLoading}
          >
            {(agentsQuery.data?.items ?? []).map((agent) => {
              const bound = boundAgentIds.has(agent.id)
              return (
                <BindingRow
                  key={agent.id}
                  title={agent.name}
                  subtitle={agent.slug}
                  checked={bound}
                  disabled={agentMutation.isPending}
                  onCheckedChange={() => agentMutation.mutate({ agent, bound })}
                />
              )
            })}
          </BindingList>
          <BindingList
            title='允许声明的宿主工具'
            loading={toolsQuery.isLoading || toolBindingsQuery.isLoading}
          >
            {(toolsQuery.data ?? []).map((tool) => {
              const bound = boundToolIds.has(tool.id)
              return (
                <BindingRow
                  key={tool.id}
                  title={tool.name}
                  subtitle={`${tool.side_effect} · ${tool.confirmation_policy}`}
                  checked={bound}
                  disabled={toolMutation.isPending}
                  onCheckedChange={() => toolMutation.mutate({ tool, bound })}
                />
              )
            })}
          </BindingList>
        </div>
        <DialogFooter>
          <Button variant='outline' onClick={() => onOpenChange(false)}>
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function SecretDialog({
  result,
  onClose,
}: {
  result: { title: string; clientId: string; secret: string } | null
  onClose: () => void
}) {
  return (
    <Dialog open={!!result} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{result?.title}</DialogTitle>
          <DialogDescription>
            关闭后无法再次查看，请立即保存到接入方服务端密钥管理系统。
          </DialogDescription>
        </DialogHeader>
        <div className='grid gap-3'>
          <ReadOnlySecret label='Client ID' value={result?.clientId ?? ''} />
          <ReadOnlySecret label='Client Secret' value={result?.secret ?? ''} />
        </div>
        <DialogFooter>
          <Button onClick={onClose}>我已保存</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ReadOnlySecret({ label, value }: { label: string; value: string }) {
  return (
    <div className='grid gap-1.5'>
      <Label>{label}</Label>
      <Input className='font-mono text-xs' readOnly value={value} />
    </div>
  )
}

function BindingList({
  title,
  loading,
  children,
}: {
  title: string
  loading: boolean
  children: ReactNode
}) {
  return (
    <div className='rounded-md border'>
      <div className='border-b px-4 py-3 font-medium'>{title}</div>
      <div className='grid gap-1 p-2'>
        {loading ? <Skeleton className='h-10 w-full' /> : children}
      </div>
    </div>
  )
}

function BindingRow({
  title,
  subtitle,
  checked,
  disabled,
  onCheckedChange,
}: {
  title: string
  subtitle: string
  checked: boolean
  disabled: boolean
  onCheckedChange: () => void
}) {
  return (
    <div className='flex items-center justify-between gap-3 rounded-md px-2 py-2 hover:bg-muted/60'>
      <div>
        <div className='font-medium'>{title}</div>
        <div className='text-xs text-muted-foreground'>{subtitle}</div>
      </div>
      <Switch
        checked={checked}
        disabled={disabled}
        onCheckedChange={onCheckedChange}
      />
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className='grid gap-1.5'>
      <Label>{label}</Label>
      {children}
    </div>
  )
}

function toClientInput(form: ClientForm): EmbedClientInput {
  const origins = form.allowed_origins
    .split(/\n|,/)
    .map((item) => item.trim().replace(/\/$/, ''))
    .filter(Boolean)
  if (!form.name.trim()) throw new Error('请输入名称')
  if (!origins.length) throw new Error('请至少填写一个 Origin')
  for (const origin of origins) {
    const parsed = new URL(origin)
    if (parsed.pathname !== '/' || parsed.search || parsed.hash) {
      throw new Error('Origin 不能包含路径、查询或片段')
    }
  }
  return {
    name: form.name.trim(),
    allowed_origins: Array.from(new Set(origins)).sort(),
    token_ttl_seconds: Number(form.token_ttl_seconds),
    max_tokens_per_minute: optionalNumber(form.max_tokens_per_minute),
    max_connections: optionalNumber(form.max_connections),
  }
}

function optionalNumber(value: string) {
  if (!value.trim()) return null
  const parsed = Number(value)
  if (!Number.isInteger(parsed) || parsed < 1) {
    throw new Error('限额必须是正整数')
  }
  return parsed
}
