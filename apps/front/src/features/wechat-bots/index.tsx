import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, MessageCircle, RefreshCw, Smartphone, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { listAgents, type Agent } from '@/api/agent'
import { listPlatforms } from '@/api/platform'
import {
  createWeChatBot,
  deleteWeChatBot,
  getWeChatBotStatus,
  listWeChatBots,
  submitWeChatBotVerifyCode,
  type WeChatBotBinding,
  type WeChatBotBindingCreated,
} from '@/api/wechat-bots'
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
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { ThemeSwitch } from '@/components/theme-switch'

const STATUS_META: Record<string, { label: string; className: string }> = {
  pending: { label: '待扫码', className: 'bg-amber-500/15 text-amber-600' },
  active: { label: '已生效', className: 'bg-emerald-500/15 text-emerald-600' },
  disabled: { label: '已停用', className: 'bg-zinc-500/15 text-zinc-600' },
  expired: { label: '已过期', className: 'bg-rose-500/15 text-rose-600' },
}

function statusBadge(status: string) {
  const meta = STATUS_META[status] ?? {
    label: status,
    className: 'bg-zinc-500/15 text-zinc-600',
  }
  return <Badge className={meta.className}>{meta.label}</Badge>
}

function isImageSource(value: string) {
  return value.startsWith('http') || value.startsWith('data:')
}

export function WeChatBotsPage() {
  const queryClient = useQueryClient()
  const [platformId, setPlatformId] = useState<number>()
  const [createOpen, setCreateOpen] = useState(false)
  const [agentId, setAgentId] = useState<string>('')
  const [created, setCreated] = useState<WeChatBotBindingCreated | null>(null)
  const [pollStatus, setPollStatus] = useState<string>('')
  const [needVerifyCode, setNeedVerifyCode] = useState(false)
  const [verifyCode, setVerifyCode] = useState('')
  const [deleting, setDeleting] = useState<WeChatBotBinding | null>(null)
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  const platformsQuery = useQuery({
    queryKey: ['platforms'],
    queryFn: listPlatforms,
  })
  const activePlatformId = platformId ?? platformsQuery.data?.[0]?.id
  const bindingsQuery = useQuery({
    queryKey: ['wechat-bots', activePlatformId],
    queryFn: () => listWeChatBots(activePlatformId!),
    enabled: activePlatformId != null,
  })
  const agentsQuery = useQuery({
    queryKey: ['agents', activePlatformId],
    queryFn: () => listAgents(activePlatformId!, { pageSize: 100 }),
    enabled: activePlatformId != null && createOpen,
  })

  const invalidateBindings = () =>
    queryClient.invalidateQueries({ queryKey: ['wechat-bots', activePlatformId] })

  const stopPolling = () => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current)
      pollTimer.current = null
    }
  }

  useEffect(() => stopPolling, [])

  const startPolling = (bindingId: number) => {
    stopPolling()
    setPollStatus('等待扫码...')
    pollTimer.current = setInterval(async () => {
      if (!activePlatformId) return
      try {
        const result = await getWeChatBotStatus(activePlatformId, bindingId)
        setPollStatus(result.message)
        if (
          ['confirmed', 'expired', 'binded_redirect', 'error', 'verify_code_blocked'].includes(
            result.status
          )
        ) {
          stopPolling()
          if (result.status === 'confirmed') toast.success('微信助手绑定成功')
          else if (result.status === 'expired' || result.status === 'binded_redirect') {
            toast.error(result.message)
          }
          await invalidateBindings()
        }
        if (result.status === 'need_verifycode') {
          stopPolling()
          setNeedVerifyCode(true)
        }
      } catch {
        setPollStatus('状态查询失败，正在自动重试...')
      }
    }, 3000)
  }

  const refreshStatus = async () => {
    if (!created || !activePlatformId) return
    setPollStatus('正在查询状态...')
    try {
      const result = await getWeChatBotStatus(activePlatformId, created.binding.id)
      setPollStatus(result.message)
      if (result.status === 'need_verifycode') {
        stopPolling()
        setNeedVerifyCode(true)
      }
      if (
        ['confirmed', 'expired', 'binded_redirect', 'error', 'verify_code_blocked'].includes(
          result.status
        )
      ) {
        stopPolling()
        if (result.status === 'confirmed') toast.success('微信助手绑定成功')
        else if (result.status !== 'error') toast.error(result.message)
        await queryClient.invalidateQueries({
          queryKey: ['wechat-bots', activePlatformId],
        })
      }
    } catch {
      setPollStatus('状态查询失败，请稍后重试')
    }
  }

  const createMutation = useMutation({
    mutationFn: async () => {
      if (!activePlatformId) throw new Error('请选择平台')
      return createWeChatBot(activePlatformId, {
        agent_id: agentId ? Number(agentId) : null,
      })
    },
    onSuccess: (result) => {
      setCreated(result)
      startPolling(result.binding.id)
      toast.success('已生成二维码，请用微信扫码')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (binding: WeChatBotBinding) =>
      deleteWeChatBot(activePlatformId!, binding.id),
    onSuccess: async () => {
      toast.success('微信助手已解绑')
      setDeleting(null)
      await invalidateBindings()
    },
  })

  const closeCreate = () => {
    stopPolling()
    setCreateOpen(false)
    setCreated(null)
    setAgentId('')
    setPollStatus('')
    setNeedVerifyCode(false)
    setVerifyCode('')
  }

  const submitVerifyCode = async () => {
    if (!created || !activePlatformId || !verifyCode.trim()) return
    const result = await submitWeChatBotVerifyCode(
      activePlatformId,
      created.binding.id,
      verifyCode.trim()
    )
    setPollStatus(result.message)
    setVerifyCode('')
    if (['confirmed', 'expired', 'binded_redirect', 'error', 'verify_code_blocked'].includes(result.status)) {
      stopPolling()
      if (result.status === 'confirmed') toast.success('微信助手绑定成功')
      else toast.error(result.message)
      await queryClient.invalidateQueries({
        queryKey: ['wechat-bots', activePlatformId],
      })
    } else if (result.status === 'need_verifycode') {
      setNeedVerifyCode(true)
    }
  }

  const copyToken = async () => {
    if (!created) return
    await navigator.clipboard.writeText(created.api_token)
    toast.success('服务 Token 已复制')
  }

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
            <h2 className='text-2xl font-bold tracking-tight'>微信助手管理</h2>
            <p className='text-muted-foreground'>
              将微信号绑定为智能助手：扫码绑定、查看状态、解绑。每个后台用户每个平台一个微信助手。
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
              onClick={() => bindingsQuery.refetch()}
              disabled={!activePlatformId || bindingsQuery.isFetching}
            >
              <RefreshCw className='size-4' />
              刷新
            </Button>
            <Button
              size='sm'
              onClick={() => setCreateOpen(true)}
              disabled={!activePlatformId}
            >
              <Smartphone className='size-4' />
              绑定微信助手
            </Button>
          </div>
        </div>

        {bindingsQuery.isLoading ? (
          <Skeleton className='h-40 w-full' />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>状态</TableHead>
                <TableHead>绑定微信号</TableHead>
                <TableHead>智能体</TableHead>
                <TableHead>最近登录</TableHead>
                <TableHead>错误信息</TableHead>
                <TableHead className='text-right'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(bindingsQuery.data ?? []).map((binding) => (
                <TableRow key={binding.id}>
                  <TableCell>{statusBadge(binding.status)}</TableCell>
                  <TableCell className='font-medium'>
                    {binding.ilink_user_id ?? '未绑定'}
                  </TableCell>
                  <TableCell>
                    {binding.agent_id != null ? `#${binding.agent_id}` : '平台默认'}
                  </TableCell>
                  <TableCell>
                    {binding.last_login_at
                      ? formatDateTime(binding.last_login_at)
                      : '-'}
                  </TableCell>
                  <TableCell className='max-w-64 truncate text-muted-foreground'>
                    {binding.last_error ?? '-'}
                  </TableCell>
                  <TableCell className='text-right'>
                    <Button
                      variant='ghost'
                      size='icon'
                      onClick={() => setDeleting(binding)}
                      disabled={!binding.is_active}
                    >
                      <Trash2 className='size-4' />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {(bindingsQuery.data ?? []).length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={6}
                    className='py-10 text-center text-muted-foreground'
                  >
                    <MessageCircle className='mx-auto mb-2 size-8' />
                    暂无绑定，点击「绑定微信助手」开始。
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        )}
      </Main>

      <Dialog open={createOpen} onOpenChange={(open) => !open && closeCreate()}>
        <DialogContent className='sm:max-w-md'>
          <DialogHeader>
            <DialogTitle>绑定微信助手</DialogTitle>
            <DialogDescription>
              选择对话智能体后生成二维码，用微信「扫一扫」确认绑定。
            </DialogDescription>
          </DialogHeader>
          {!created ? (
            <div className='space-y-4'>
              <div className='space-y-2'>
                <Label>对话智能体（留空使用平台默认）</Label>
                <Select value={agentId} onValueChange={setAgentId}>
                  <SelectTrigger>
                    <SelectValue placeholder='平台默认智能体' />
                  </SelectTrigger>
                  <SelectContent>
                    {(agentsQuery.data?.items ?? []).map((agent: Agent) => (
                      <SelectItem key={agent.id} value={agent.id.toString()}>
                        {agent.name} ({agent.slug})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <DialogFooter>
                <Button
                  onClick={() => createMutation.mutate()}
                  disabled={createMutation.isPending}
                >
                  {createMutation.isPending ? '生成中...' : '生成二维码'}
                </Button>
              </DialogFooter>
            </div>
          ) : (
            <div className='flex flex-col items-center gap-3'>
              <div className='rounded-lg border p-3'>
                {isImageSource(created.qrcode) ? (
                  <img
                    src={created.qrcode}
                    alt='微信绑定二维码'
                    className='size-52 object-contain'
                  />
                ) : (
                  <p className='max-w-64 break-all text-xs'>{created.qrcode}</p>
                )}
              </div>
              <p className='text-sm text-muted-foreground'>{pollStatus}</p>
              <Button
                variant='outline'
                size='sm'
                onClick={refreshStatus}
                disabled={!created}
              >
                <RefreshCw className='size-4' />
                重新查询状态
              </Button>
              {needVerifyCode && (
                <div className='flex w-full items-center gap-2'>
                  <Input
                    value={verifyCode}
                    onChange={(event) => setVerifyCode(event.target.value)}
                    placeholder='输入微信显示的 6 位配对码'
                    maxLength={12}
                  />
                  <Button size='sm' onClick={submitVerifyCode}>
                    提交
                  </Button>
                </div>
              )}
              <div className='w-full space-y-1'>
                <Label>服务 Token（仅显示一次，请妥善保存）</Label>
                <div className='flex items-center gap-2'>
                  <code className='min-w-0 flex-1 truncate rounded-md bg-muted px-2 py-1 text-xs'>
                    {created.api_token}
                  </code>
                  <Button variant='outline' size='sm' onClick={copyToken}>
                    <Copy className='size-4' />
                    复制
                  </Button>
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={deleting != null}
        onOpenChange={(open) => !open && setDeleting(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>解绑微信助手</AlertDialogTitle>
            <AlertDialogDescription>
              解绑后将清除微信登录凭证并停止该实例，确认继续？
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleting && deleteMutation.mutate(deleting)}
            >
              确认解绑
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
