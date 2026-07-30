import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Eye, FileCode2, Link2, RefreshCw, Server } from 'lucide-react'
import { toast } from 'sonner'
import { listAgents } from '@/api/agent'
import { listEmbedClients } from '@/api/embed-clients'
import {
  bindAgentHostTool,
  bindEmbedClientHostTool,
  createHostTool,
  listAgentHostTools,
  listEmbedClientHostTools,
  listHostToolAudits,
  listHostTools,
  unbindAgentHostTool,
  unbindEmbedClientHostTool,
  updateHostTool,
  type HostToolConfirmationPolicy,
  type HostToolPolicy,
  type HostToolPolicyInput,
  type HostToolSideEffect,
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

type ToolForm = {
  name: string
  description: string
  input_schema: string
  output_schema: string
  side_effect: HostToolSideEffect
  confirmation_policy: HostToolConfirmationPolicy
  is_enabled: boolean
}

const defaultForm: ToolForm = {
  name: '',
  description: '',
  input_schema: '{\n  "type": "object",\n  "properties": {}\n}',
  output_schema: '',
  side_effect: 'external',
  confirmation_policy: 'always',
  is_enabled: true,
}

const sideEffects: HostToolSideEffect[] = [
  'none',
  'navigation',
  'write',
  'financial',
  'external',
]

export function HostToolsPage() {
  const queryClient = useQueryClient()
  const [platformId, setPlatformId] = useState<number>()
  const [editing, setEditing] = useState<HostToolPolicy | null | undefined>()
  const [bindingTool, setBindingTool] = useState<HostToolPolicy | null>(null)
  const [auditsOpen, setAuditsOpen] = useState(false)
  const platformsQuery = useQuery({
    queryKey: ['platforms'],
    queryFn: listPlatforms,
  })
  const activePlatformId = platformId ?? platformsQuery.data?.[0]?.id
  const toolsQuery = useQuery({
    queryKey: ['host-tools', activePlatformId],
    queryFn: () => listHostTools(activePlatformId!),
    enabled: activePlatformId != null,
  })
  const invalidateTools = () =>
    queryClient.invalidateQueries({
      queryKey: ['host-tools', activePlatformId],
    })
  const saveMutation = useMutation({
    mutationFn: (form: ToolForm) => {
      if (!activePlatformId) throw new Error('请选择平台')
      const input = toToolInput(form)
      return editing
        ? updateHostTool(activePlatformId, editing.id, {
            description: input.description,
            input_schema: input.input_schema,
            output_schema: input.output_schema,
            side_effect: input.side_effect,
            confirmation_policy: input.confirmation_policy,
            is_enabled: form.is_enabled,
          })
        : createHostTool(activePlatformId, input)
    },
    onSuccess: async () => {
      toast.success(editing ? '宿主工具已更新' : '宿主工具已创建')
      setEditing(undefined)
      await invalidateTools()
    },
  })
  const toggleMutation = useMutation({
    mutationFn: ({
      tool,
      is_enabled,
    }: {
      tool: HostToolPolicy
      is_enabled: boolean
    }) =>
      updateHostTool(activePlatformId!, tool.id, {
        description: tool.description,
        input_schema: tool.input_schema,
        output_schema: tool.output_schema,
        side_effect: tool.side_effect,
        confirmation_policy: tool.confirmation_policy,
        is_enabled,
      }),
    onSuccess: async () => {
      toast.success('工具状态已更新')
      await invalidateTools()
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
            <h2 className='text-2xl font-bold tracking-tight'>宿主工具策略</h2>
            <p className='text-muted-foreground'>
              管理浏览器宿主工具白名单、确认策略和调用审计。
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
              onClick={() => toolsQuery.refetch()}
              disabled={!activePlatformId || toolsQuery.isFetching}
            >
              <RefreshCw className='size-4' />
              刷新
            </Button>
            <Button
              variant='outline'
              size='sm'
              onClick={() => setAuditsOpen(true)}
              disabled={!activePlatformId}
            >
              <Eye className='size-4' />
              审计
            </Button>
            <Button
              size='sm'
              onClick={() => setEditing(null)}
              disabled={!activePlatformId}
            >
              <FileCode2 className='size-4' />
              新建策略
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
                <TableHead>工具</TableHead>
                <TableHead>描述</TableHead>
                <TableHead>策略</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className='w-40 text-end'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {toolsQuery.isLoading
                ? Array.from({ length: 4 }).map((_, index) => (
                    <TableRow key={index}>
                      <TableCell colSpan={5}>
                        <Skeleton className='h-8 w-full' />
                      </TableCell>
                    </TableRow>
                  ))
                : (toolsQuery.data ?? []).map((tool) => (
                    <TableRow key={tool.id}>
                      <TableCell>
                        <div className='font-mono text-sm font-medium'>
                          {tool.name}
                        </div>
                        <div className='text-xs text-muted-foreground'>
                          ID {tool.id}
                        </div>
                      </TableCell>
                      <TableCell className='max-w-md truncate'>
                        {tool.description}
                      </TableCell>
                      <TableCell>
                        <div className='flex flex-wrap gap-1'>
                          <Badge
                            variant={
                              tool.side_effect === 'none'
                                ? 'outline'
                                : 'secondary'
                            }
                          >
                            {tool.side_effect}
                          </Badge>
                          <Badge variant='outline'>
                            {tool.confirmation_policy}
                          </Badge>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className='flex items-center gap-2'>
                          <Switch
                            checked={tool.is_enabled}
                            disabled={toggleMutation.isPending}
                            onCheckedChange={(is_enabled) =>
                              toggleMutation.mutate({ tool, is_enabled })
                            }
                          />
                          <Badge
                            variant={tool.is_enabled ? 'default' : 'secondary'}
                          >
                            {tool.is_enabled ? '启用' : '停用'}
                          </Badge>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className='flex justify-end gap-1'>
                          <Button
                            size='icon'
                            variant='ghost'
                            onClick={() => setBindingTool(tool)}
                          >
                            <Link2 className='size-4' />
                            <span className='sr-only'>绑定</span>
                          </Button>
                          <Button
                            size='icon'
                            variant='ghost'
                            onClick={() => setEditing(tool)}
                          >
                            <FileCode2 className='size-4' />
                            <span className='sr-only'>编辑</span>
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
              {!toolsQuery.isLoading && !toolsQuery.data?.length && (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className='h-24 text-center text-muted-foreground'
                  >
                    暂无宿主工具策略
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
        <div className='text-sm text-muted-foreground'>
          共 {toolsQuery.data?.length ?? 0} 个宿主工具策略
        </div>
      </Main>
      <ToolDialog
        key={editing ? editing.id : 'new'}
        tool={editing && editing.id ? editing : null}
        open={editing !== undefined}
        onOpenChange={(open) => !open && setEditing(undefined)}
        isSaving={saveMutation.isPending}
        onSubmit={(form) => saveMutation.mutate(form)}
      />
      {activePlatformId && bindingTool && (
        <BindingDialog
          platformId={activePlatformId}
          tool={bindingTool}
          open
          onOpenChange={(open) => !open && setBindingTool(null)}
        />
      )}
      {activePlatformId && (
        <AuditsDialog
          platformId={activePlatformId}
          open={auditsOpen}
          onOpenChange={setAuditsOpen}
        />
      )}
    </>
  )
}

function ToolDialog({
  tool,
  open,
  onOpenChange,
  isSaving,
  onSubmit,
}: {
  tool: HostToolPolicy | null
  open: boolean
  onOpenChange: (open: boolean) => void
  isSaving: boolean
  onSubmit: (form: ToolForm) => void
}) {
  const [form, setForm] = useState<ToolForm>(
    tool
      ? {
          name: tool.name,
          description: tool.description,
          input_schema: JSON.stringify(tool.input_schema, null, 2),
          output_schema: tool.output_schema
            ? JSON.stringify(tool.output_schema, null, 2)
            : '',
          side_effect: tool.side_effect,
          confirmation_policy: tool.confirmation_policy,
          is_enabled: tool.is_enabled,
        }
      : defaultForm
  )
  const [error, setError] = useState('')
  const update = (patch: Partial<ToolForm>) =>
    setForm((current) => ({ ...current, ...patch }))
  const submit = () => {
    try {
      toToolInput(form)
      setError('')
      onSubmit(form)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '表单无效')
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-h-[90vh] max-w-3xl overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>{tool ? '编辑宿主工具' : '新建宿主工具'}</DialogTitle>
          <DialogDescription>
            页面注册的工具只有匹配后台策略后才可能被 Agent 调用。
          </DialogDescription>
        </DialogHeader>
        <div className='grid gap-4'>
          <div className='grid gap-4 sm:grid-cols-2'>
            <Field label='工具名称'>
              <Input
                value={form.name}
                disabled={!!tool}
                placeholder='orders.get_status'
                onChange={(event) => update({ name: event.target.value })}
              />
            </Field>
            <Field label='确认策略'>
              <Select
                value={form.confirmation_policy}
                onValueChange={(value) =>
                  update({
                    confirmation_policy: value as HostToolConfirmationPolicy,
                  })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value='always'>always</SelectItem>
                  <SelectItem value='auto'>auto</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </div>
          <Field label='描述'>
            <Input
              value={form.description}
              onChange={(event) => update({ description: event.target.value })}
            />
          </Field>
          <Field label='副作用'>
            <Select
              value={form.side_effect}
              onValueChange={(value) =>
                update({ side_effect: value as HostToolSideEffect })
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {sideEffects.map((item) => (
                  <SelectItem key={item} value={item}>
                    {item}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <div className='grid gap-4 md:grid-cols-2'>
            <Field label='Input Schema JSON'>
              <Textarea
                rows={10}
                className='font-mono text-sm'
                value={form.input_schema}
                onChange={(event) =>
                  update({ input_schema: event.target.value })
                }
              />
            </Field>
            <Field label='Output Schema JSON'>
              <Textarea
                rows={10}
                className='font-mono text-sm'
                value={form.output_schema}
                placeholder='可选'
                onChange={(event) =>
                  update({ output_schema: event.target.value })
                }
              />
            </Field>
          </div>
          {tool && (
            <div className='flex items-center justify-between rounded-md border p-3'>
              <Label>启用策略</Label>
              <Switch
                checked={form.is_enabled}
                onCheckedChange={(is_enabled) => update({ is_enabled })}
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
  tool,
  open,
  onOpenChange,
}: {
  platformId: number
  tool: HostToolPolicy
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [agentId, setAgentId] = useState<number>()
  const [clientId, setClientId] = useState<string>()
  const agentsQuery = useQuery({
    queryKey: ['agents', platformId],
    queryFn: () => listAgents(platformId),
    enabled: open,
  })
  const clientsQuery = useQuery({
    queryKey: ['embed-clients', platformId],
    queryFn: () => listEmbedClients(platformId),
    enabled: open,
  })
  const agentBindingsQuery = useQuery({
    queryKey: ['agent-host-tools', platformId, agentId],
    queryFn: () => listAgentHostTools(platformId, agentId!),
    enabled: agentId != null,
  })
  const clientBindingsQuery = useQuery({
    queryKey: ['embed-client-host-tools', platformId, clientId],
    queryFn: () => listEmbedClientHostTools(platformId, clientId!),
    enabled: clientId != null,
  })
  const agentBound = agentBindingsQuery.data?.some(
    (item) => item.tool_id === tool.id
  )
  const clientBound = clientBindingsQuery.data?.some(
    (item) => item.tool_id === tool.id
  )
  const agentMutation = useMutation({
    mutationFn: () =>
      agentBound
        ? unbindAgentHostTool(platformId, agentId!, tool.id)
        : bindAgentHostTool(platformId, agentId!, tool.id),
    onSuccess: async () => {
      toast.success('Agent 绑定已更新')
      await queryClient.invalidateQueries({
        queryKey: ['agent-host-tools', platformId, agentId],
      })
    },
  })
  const clientMutation = useMutation({
    mutationFn: () =>
      clientBound
        ? unbindEmbedClientHostTool(platformId, clientId!, tool.id)
        : bindEmbedClientHostTool(platformId, clientId!, tool.id),
    onSuccess: async () => {
      toast.success('Client 绑定已更新')
      await queryClient.invalidateQueries({
        queryKey: ['embed-client-host-tools', platformId, clientId],
      })
    },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-w-2xl'>
        <DialogHeader>
          <DialogTitle>{tool.name} · 绑定配置</DialogTitle>
          <DialogDescription>
            工具必须同时绑定 Agent 和 Embed
            Client，且页面实际注册后才会进入可调用集合。
          </DialogDescription>
        </DialogHeader>
        <div className='grid gap-4 md:grid-cols-2'>
          <BindingPicker
            title='Agent 绑定'
            icon={<Bot className='size-4' />}
            value={agentId?.toString()}
            placeholder='选择 Agent'
            onValueChange={(value) => setAgentId(Number(value))}
            items={(agentsQuery.data?.items ?? []).map((agent) => ({
              value: agent.id.toString(),
              label: `${agent.name} (${agent.slug})`,
            }))}
            checked={!!agentBound}
            disabled={!agentId || agentMutation.isPending}
            onToggle={() => agentMutation.mutate()}
          />
          <BindingPicker
            title='Embed Client 绑定'
            icon={<KeyIcon />}
            value={clientId}
            placeholder='选择 Client'
            onValueChange={setClientId}
            items={(clientsQuery.data ?? []).map((client) => ({
              value: client.client_id,
              label: `${client.name} (${client.client_id})`,
            }))}
            checked={!!clientBound}
            disabled={!clientId || clientMutation.isPending}
            onToggle={() => clientMutation.mutate()}
          />
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

function AuditsDialog({
  platformId,
  open,
  onOpenChange,
}: {
  platformId: number
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const auditsQuery = useQuery({
    queryKey: ['host-tool-audits', platformId],
    queryFn: () => listHostToolAudits(platformId),
    enabled: open,
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-h-[90vh] max-w-5xl overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>宿主工具最近审计</DialogTitle>
          <DialogDescription>
            展示最近调用状态和错误摘要，敏感参数由后端脱敏。
          </DialogDescription>
        </DialogHeader>
        <div className='overflow-hidden rounded-md border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>调用</TableHead>
                <TableHead>Agent / 用户</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>错误</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {auditsQuery.isLoading ? (
                <TableRow>
                  <TableCell colSpan={4}>
                    <Skeleton className='h-8 w-full' />
                  </TableCell>
                </TableRow>
              ) : (
                (auditsQuery.data ?? []).map((audit) => (
                  <TableRow key={audit.id}>
                    <TableCell>
                      <div className='font-mono text-sm'>{audit.tool_name}</div>
                      <div className='font-mono text-xs text-muted-foreground'>
                        {audit.call_id}
                      </div>
                    </TableCell>
                    <TableCell className='text-sm'>
                      Agent {audit.agent_id} · EndUser{' '}
                      {audit.platform_end_user_id}
                    </TableCell>
                    <TableCell>
                      <Badge variant='outline'>{audit.status}</Badge>
                    </TableCell>
                    <TableCell className='max-w-md truncate'>
                      {audit.error ?? '-'}
                    </TableCell>
                  </TableRow>
                ))
              )}
              {!auditsQuery.isLoading && !auditsQuery.data?.length && (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className='h-20 text-center text-muted-foreground'
                  >
                    暂无审计记录
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
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

function BindingPicker({
  title,
  icon,
  value,
  placeholder,
  onValueChange,
  items,
  checked,
  disabled,
  onToggle,
}: {
  title: string
  icon: ReactNode
  value?: string
  placeholder: string
  onValueChange: (value: string) => void
  items: { value: string; label: string }[]
  checked: boolean
  disabled: boolean
  onToggle: () => void
}) {
  return (
    <div className='grid gap-3 rounded-md border p-4'>
      <div className='flex items-center gap-2 font-medium'>
        {icon}
        {title}
      </div>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger>
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <div className='flex items-center justify-between rounded-md bg-muted/40 px-3 py-2'>
        <span className='text-sm'>{checked ? '已绑定' : '未绑定'}</span>
        <Switch
          checked={checked}
          disabled={disabled}
          onCheckedChange={onToggle}
        />
      </div>
    </div>
  )
}

function KeyIcon() {
  return <Link2 className='size-4' />
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className='grid gap-1.5'>
      <Label>{label}</Label>
      {children}
    </div>
  )
}

function toToolInput(form: ToolForm): HostToolPolicyInput {
  if (!form.name.trim()) throw new Error('请输入工具名称')
  if (!form.description.trim()) throw new Error('请输入描述')
  const inputSchema = parseObject(form.input_schema, 'Input Schema')
  const outputSchema = form.output_schema.trim()
    ? parseObject(form.output_schema, 'Output Schema')
    : null
  return {
    name: form.name.trim(),
    description: form.description.trim(),
    input_schema: inputSchema,
    output_schema: outputSchema,
    side_effect: form.side_effect,
    confirmation_policy: form.confirmation_policy,
  }
}

function parseObject(value: string, label: string): Record<string, unknown> {
  const parsed = JSON.parse(value)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON 对象`)
  }
  if ('type' in parsed && parsed.type !== 'object') {
    throw new Error(`${label} 的 type 必须是 object`)
  }
  return parsed as Record<string, unknown>
}
