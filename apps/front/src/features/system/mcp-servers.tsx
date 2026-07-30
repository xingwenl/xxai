import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Cable, Edit, Eye, Plus, RefreshCw, Server, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { listAgents, type Agent } from '@/api/agent'
import {
  bindMcpServer,
  createMcpServer,
  deleteMcpServer,
  listMcpAudits,
  listMcpBindings,
  listMcpServerTools,
  listMcpServers,
  syncMcpServerTools,
  unbindMcpServer,
  updateMcpServer,
  updateMcpToolPolicy,
  type McpServer,
  type McpServerInput,
  type McpTool,
} from '@/api/mcp-servers'
import { listPlatforms } from '@/api/platform'
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

type ServerForm = McpServerInput & { id?: number; is_active: boolean }
const emptyForm: ServerForm = {
  name: '',
  slug: '',
  endpoint_url: '',
  auth_headers: {},
  is_active: true,
}

export function McpServersPage() {
  const queryClient = useQueryClient()
  const [platformId, setPlatformId] = useState<number>()
  const [editing, setEditing] = useState<ServerForm | null>(null)
  const [deleting, setDeleting] = useState<McpServer | null>(null)
  const [toolsServer, setToolsServer] = useState<McpServer | null>(null)
  const [bindingServer, setBindingServer] = useState<McpServer | null>(null)
  const [auditsOpen, setAuditsOpen] = useState(false)
  const platformsQuery = useQuery({
    queryKey: ['platforms'],
    queryFn: listPlatforms,
  })
  const activePlatformId = platformId ?? platformsQuery.data?.[0]?.id
  const serversQuery = useQuery({
    queryKey: ['mcp-servers', activePlatformId],
    queryFn: () => listMcpServers(activePlatformId!),
    enabled: activePlatformId != null,
  })
  const invalidateServers = () =>
    queryClient.invalidateQueries({
      queryKey: ['mcp-servers', activePlatformId],
    })
  const saveMutation = useMutation({
    mutationFn: (form: ServerForm) => {
      if (!activePlatformId) throw new Error('请选择平台')
      return form.id
        ? updateMcpServer(activePlatformId, form.id, {
            name: form.name,
            endpoint_url: form.endpoint_url,
            auth_headers: Object.keys(form.auth_headers).length
              ? form.auth_headers
              : undefined,
            is_active: form.is_active,
          })
        : createMcpServer(activePlatformId, form)
    },
    onSuccess: async () => {
      toast.success(editing?.id ? 'MCP 服务已更新' : 'MCP 服务已创建')
      setEditing(null)
      await invalidateServers()
    },
  })
  const toggleMutation = useMutation({
    mutationFn: ({
      server,
      is_active,
    }: {
      server: McpServer
      is_active: boolean
    }) => updateMcpServer(activePlatformId!, server.id, { is_active }),
    onSuccess: async () => {
      toast.success('服务状态已更新')
      await invalidateServers()
    },
  })
  const deleteMutation = useMutation({
    mutationFn: (server: McpServer) =>
      deleteMcpServer(activePlatformId!, server.id),
    onSuccess: async () => {
      toast.success('MCP 服务已删除')
      setDeleting(null)
      await invalidateServers()
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
            <h2 className='text-2xl font-bold tracking-tight'>MCP 服务管理</h2>
            <p className='text-muted-foreground'>
              配置远程工具服务、调用策略和智能体绑定。
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
              onClick={() => serversQuery.refetch()}
              disabled={serversQuery.isFetching}
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
              onClick={() => setEditing(emptyForm)}
              disabled={!activePlatformId}
            >
              <Plus className='size-4' />
              新增服务
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
                <TableHead>服务</TableHead>
                <TableHead>Endpoint</TableHead>
                <TableHead>认证</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className='w-48 text-end'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {serversQuery.isLoading
                ? Array.from({ length: 4 }).map((_, i) => (
                    <TableRow key={i}>
                      <TableCell colSpan={5}>
                        <Skeleton className='h-8 w-full' />
                      </TableCell>
                    </TableRow>
                  ))
                : (serversQuery.data?.items ?? []).map((server) => (
                    <TableRow key={server.id}>
                      <TableCell>
                        <div className='flex items-center gap-3'>
                          <div className='flex size-9 items-center justify-center rounded-md bg-muted'>
                            <Cable className='size-4 text-muted-foreground' />
                          </div>
                          <div>
                            <div className='font-medium'>{server.name}</div>
                            <div className='text-xs text-muted-foreground'>
                              {server.slug} · ID {server.id}
                            </div>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className='max-w-72 truncate font-mono text-xs'>
                        {server.endpoint_url}
                      </TableCell>
                      <TableCell>
                        {server.has_auth_headers ? (
                          <Badge variant='outline'>已配置</Badge>
                        ) : (
                          <span className='text-muted-foreground'>无</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className='flex items-center gap-2'>
                          <Switch
                            checked={server.is_active}
                            disabled={toggleMutation.isPending}
                            onCheckedChange={(is_active) =>
                              toggleMutation.mutate({ server, is_active })
                            }
                          />
                          <Badge
                            variant={server.is_active ? 'default' : 'secondary'}
                          >
                            {server.is_active ? '启用' : '停用'}
                          </Badge>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className='flex justify-end gap-1'>
                          <Button
                            size='icon'
                            variant='ghost'
                            onClick={() => setToolsServer(server)}
                          >
                            <Cable className='size-4' />
                            <span className='sr-only'>工具</span>
                          </Button>
                          <Button
                            size='icon'
                            variant='ghost'
                            onClick={() => setBindingServer(server)}
                          >
                            <Server className='size-4' />
                            <span className='sr-only'>绑定</span>
                          </Button>
                          <Button
                            size='icon'
                            variant='ghost'
                            onClick={() =>
                              setEditing({
                                ...server,
                                auth_headers: {},
                                is_active: server.is_active,
                              })
                            }
                          >
                            <Edit className='size-4' />
                            <span className='sr-only'>编辑</span>
                          </Button>
                          <Button
                            size='icon'
                            variant='ghost'
                            className='text-destructive hover:text-destructive'
                            onClick={() => setDeleting(server)}
                          >
                            <Trash2 className='size-4' />
                            <span className='sr-only'>删除</span>
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
              {!serversQuery.isLoading && !serversQuery.data?.items.length && (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className='h-24 text-center text-muted-foreground'
                  >
                    暂无 MCP 服务
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
        <div className='text-sm text-muted-foreground'>
          共 {serversQuery.data?.total ?? 0} 个服务
        </div>
      </Main>
      <ServerDialog
        key={editing ? (editing.id ?? 'new') : 'closed'}
        form={editing}
        open={!!editing}
        onOpenChange={(open) => !open && setEditing(null)}
        isSaving={saveMutation.isPending}
        onSubmit={(form) => saveMutation.mutate(form)}
      />
      <ToolsDialog
        platformId={activePlatformId}
        server={toolsServer}
        open={!!toolsServer}
        onOpenChange={(open) => !open && setToolsServer(null)}
      />
      <BindingDialog
        platformId={activePlatformId}
        server={bindingServer}
        open={!!bindingServer}
        onOpenChange={(open) => !open && setBindingServer(null)}
      />
      <AuditsDialog
        platformId={activePlatformId}
        open={auditsOpen}
        onOpenChange={setAuditsOpen}
      />
      <AlertDialog
        open={!!deleting}
        onOpenChange={(open) => !open && setDeleting(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除 MCP 服务</AlertDialogTitle>
            <AlertDialogDescription>
              有调用审计的服务无法硬删除，删除失败时请改为停用。无审计服务及其工具、绑定会永久删除。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              className='text-destructive-foreground bg-destructive hover:bg-destructive/90'
              onClick={() => deleting && deleteMutation.mutate(deleting)}
            >
              确认删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function ServerDialog({
  form,
  open,
  onOpenChange,
  isSaving,
  onSubmit,
}: {
  form: ServerForm | null
  open: boolean
  onOpenChange: (open: boolean) => void
  isSaving: boolean
  onSubmit: (form: ServerForm) => void
}) {
  const [value, setValue] = useState<ServerForm>(form ?? emptyForm)
  if (!form) return null
  const update = (patch: Partial<ServerForm>) =>
    setValue((current) => ({ ...current, ...patch }))
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {form.id ? '编辑 MCP 服务' : '新增 MCP 服务'}
          </DialogTitle>
          <DialogDescription>
            认证头只提交并加密保存，服务端会校验 endpoint 的安全性。
          </DialogDescription>
        </DialogHeader>
        <div className='grid gap-4'>
          <Field label='名称'>
            <Input
              value={value.name}
              onChange={(event) => update({ name: event.target.value })}
            />
          </Field>
          <Field label='Slug'>
            <Input
              value={value.slug}
              disabled={!!form.id}
              onChange={(event) => update({ slug: event.target.value })}
            />
          </Field>
          <Field label='Endpoint URL'>
            <Input
              value={value.endpoint_url}
              placeholder='https://example.com/mcp'
              onChange={(event) => update({ endpoint_url: event.target.value })}
            />
          </Field>
          <Field label='认证头 JSON'>
            <Textarea
              rows={5}
              className='font-mono text-sm'
              placeholder='{"Authorization":"Bearer ..."}'
              value={JSON.stringify(value.auth_headers, null, 2)}
              onChange={(event) => {
                try {
                  const headers = JSON.parse(event.target.value)
                  if (
                    headers &&
                    typeof headers === 'object' &&
                    !Array.isArray(headers)
                  )
                    update({ auth_headers: headers })
                } catch {
                  /* 提交时由后端校验 */
                }
              }}
            />
          </Field>
          {form.id && (
            <div className='flex items-center justify-between rounded-md border p-3'>
              <Label>启用服务</Label>
              <Switch
                checked={value.is_active}
                onCheckedChange={(is_active) => update({ is_active })}
              />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button onClick={() => onSubmit(value)} disabled={isSaving}>
            {isSaving ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
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

function ToolsDialog({
  platformId,
  server,
  open,
  onOpenChange,
}: {
  platformId?: number
  server: McpServer | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const toolsQuery = useQuery({
    queryKey: ['mcp-tools', platformId, server?.id],
    queryFn: () => listMcpServerTools(platformId!, server!.id),
    enabled: open && !!platformId && !!server,
  })
  const syncMutation = useMutation({
    mutationFn: () => syncMcpServerTools(platformId!, server!.id),
    onSuccess: async (tools) => {
      toast.success(`已同步 ${tools.length} 个工具`)
      await queryClient.invalidateQueries({
        queryKey: ['mcp-tools', platformId, server?.id],
      })
    },
  })
  const policyMutation = useMutation({
    mutationFn: ({
      tool,
      is_allowed,
    }: {
      tool: McpTool
      is_allowed: boolean
    }) =>
      updateMcpToolPolicy(platformId!, tool.id, {
        is_allowed,
        side_effect: tool.side_effect,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['mcp-tools', platformId, server?.id],
      })
    },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-w-4xl'>
        <DialogHeader>
          <DialogTitle>{server?.name} · 工具策略</DialogTitle>
          <DialogDescription>
            同步后 schema 发生变化的工具会自动恢复为禁止调用。
          </DialogDescription>
        </DialogHeader>
        <div className='flex justify-end'>
          <Button
            size='sm'
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
          >
            <RefreshCw className='size-4' />
            同步工具
          </Button>
        </div>
        <div className='max-h-[55vh] overflow-auto rounded-md border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>工具</TableHead>
                <TableHead>描述</TableHead>
                <TableHead>副作用</TableHead>
                <TableHead>允许调用</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {toolsQuery.isLoading ? (
                <TableRow>
                  <TableCell colSpan={4}>
                    <Skeleton className='h-8 w-full' />
                  </TableCell>
                </TableRow>
              ) : (
                (toolsQuery.data ?? []).map((tool) => (
                  <TableRow key={tool.id}>
                    <TableCell className='font-mono text-sm'>
                      {tool.name}
                    </TableCell>
                    <TableCell className='max-w-md truncate'>
                      {tool.description || '-'}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          tool.side_effect === 'none' ? 'outline' : 'secondary'
                        }
                      >
                        {tool.side_effect}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Switch
                        checked={tool.is_allowed}
                        onCheckedChange={(is_allowed) =>
                          policyMutation.mutate({ tool, is_allowed })
                        }
                        disabled={policyMutation.isPending}
                      />
                    </TableCell>
                  </TableRow>
                ))
              )}
              {!toolsQuery.isLoading && !toolsQuery.data?.length && (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className='h-20 text-center text-muted-foreground'
                  >
                    暂无工具，请先同步
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

function BindingDialog({
  platformId,
  server,
  open,
  onOpenChange,
}: {
  platformId?: number
  server: McpServer | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [agentId, setAgentId] = useState<number>()
  const agentsQuery = useQuery({
    queryKey: ['agents', platformId],
    queryFn: () => listAgents(platformId!),
    enabled: open && !!platformId,
  })
  const bindingsQuery = useQuery({
    queryKey: ['mcp-bindings', platformId, agentId],
    queryFn: () => listMcpBindings(platformId!, agentId!),
    enabled: !!platformId && !!agentId,
  })
  const bindMutation = useMutation({
    mutationFn: () => bindMcpServer(platformId!, agentId!, server!.id),
    onSuccess: async () => {
      toast.success('服务已绑定')
      await queryClient.invalidateQueries({
        queryKey: ['mcp-bindings', platformId, agentId],
      })
    },
  })
  const unbindMutation = useMutation({
    mutationFn: () => unbindMcpServer(platformId!, agentId!, server!.id),
    onSuccess: async () => {
      toast.success('服务已解绑')
      await queryClient.invalidateQueries({
        queryKey: ['mcp-bindings', platformId, agentId],
      })
    },
  })
  const bound = bindingsQuery.data?.some(
    (item) => item.server_id === server?.id
  )
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{server?.name} · 绑定智能体</DialogTitle>
        </DialogHeader>
        <Select
          value={agentId?.toString()}
          onValueChange={(value) => setAgentId(Number(value))}
        >
          <SelectTrigger>
            <SelectValue placeholder='选择智能体' />
          </SelectTrigger>
          <SelectContent>
            {(agentsQuery.data?.items ?? []).map((agent: Agent) => (
              <SelectItem key={agent.id} value={agent.id.toString()}>
                {agent.name} ({agent.slug})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {agentId && (
          <div className='rounded-md border p-3 text-sm'>
            {bound ? (
              <div className='flex items-center justify-between'>
                <span>当前已绑定</span>
                <Button
                  size='sm'
                  variant='outline'
                  onClick={() => unbindMutation.mutate()}
                >
                  解绑
                </Button>
              </div>
            ) : (
              <div className='flex items-center justify-between'>
                <span>当前未绑定</span>
                <Button size='sm' onClick={() => bindMutation.mutate()}>
                  绑定
                </Button>
              </div>
            )}
          </div>
        )}
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
  platformId?: number
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const auditsQuery = useQuery({
    queryKey: ['mcp-audits', platformId],
    queryFn: () => listMcpAudits(platformId!),
    enabled: open && !!platformId,
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-w-5xl'>
        <DialogHeader>
          <DialogTitle>MCP 调用审计</DialogTitle>
          <DialogDescription>
            仅展示最近 100 条调用记录，敏感参数由后端脱敏。
          </DialogDescription>
        </DialogHeader>
        <div className='max-h-[60vh] overflow-auto rounded-md border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>工具</TableHead>
                <TableHead>Agent</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>开始时间</TableHead>
                <TableHead>错误</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {auditsQuery.isLoading ? (
                <TableRow>
                  <TableCell colSpan={5}>
                    <Skeleton className='h-8 w-full' />
                  </TableCell>
                </TableRow>
              ) : (
                (auditsQuery.data ?? []).map((audit) => (
                  <TableRow key={audit.id}>
                    <TableCell className='font-mono'>
                      {audit.tool_name}
                    </TableCell>
                    <TableCell>{audit.agent_id}</TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          audit.status === 'completed' ? 'default' : 'secondary'
                        }
                      >
                        {audit.status}
                      </Badge>
                    </TableCell>
                    <TableCell className='text-xs'>
                      {formatDateTime(audit.started_at)}
                    </TableCell>
                    <TableCell className='max-w-64 truncate text-destructive'>
                      {audit.error || '-'}
                    </TableCell>
                  </TableRow>
                ))
              )}
              {!auditsQuery.isLoading && !auditsQuery.data?.length && (
                <TableRow>
                  <TableCell
                    colSpan={5}
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
