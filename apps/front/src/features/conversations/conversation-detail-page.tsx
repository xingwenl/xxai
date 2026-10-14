import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { ArrowLeft, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { deleteConversation, getConversation } from '@/api/conversation'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { ThemeSwitch } from '@/components/theme-switch'
import { formatDateTime } from '@/lib/time'
import { ConversationHistoryIsland } from './components/conversation-history-island'
import { PlatformPicker } from './components/platform-picker'
import { useActivePlatform } from './components/use-active-platform'

const routeApi = getRouteApi('/_authenticated/conversations/$conversationId')

const PRINCIPAL_TYPE_TEXT: Record<string, string> = {
  user: '后台用户',
  end_user: '终端用户',
}

/** 会话状态到展示文案的映射：软删除的会话在后台仍然可读。 */
const STATUS_TEXT: Record<string, string> = {
  active: '正常',
  deleted: '已移除',
}

function StatItem({ label, value }: { label: string; value: string | number }) {
  return (
    <div className='rounded-md border bg-muted/20 p-3'>
      <div className='text-muted-foreground text-xs'>{label}</div>
      <div className='mt-1 text-lg font-semibold'>{value}</div>
    </div>
  )
}

/**
 * 会话记录第三层：单条会话的完整内容。
 *
 * 消息正文与 Agent 执行过程直接复用 ai-sdk 的会话历史组件（与终端用户侧看到的
 * 是同一套渲染），本页只补上后台需要的会话头、用量汇总与移除操作。
 */
export function ConversationDetailPage() {
  const { conversationId } = routeApi.useParams()
  const search = routeApi.useSearch()
  const navigate = routeApi.useNavigate()
  const queryClient = useQueryClient()
  const {
    activePlatformId,
    setPlatformId,
    platforms,
    isLoading: platformsLoading,
  } = useActivePlatform(search.platform)

  const conversationIdNumber = Number(conversationId)
  const enabled = activePlatformId != null && Number.isFinite(conversationIdNumber)

  const [showAgentLoop, setShowAgentLoop] = useState(true)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const detailQuery = useQuery({
    queryKey: ['conversation', activePlatformId, conversationIdNumber],
    queryFn: () => getConversation(activePlatformId!, conversationIdNumber),
    enabled,
  })

  const deleteMutation = useMutation({
    mutationFn: () =>
      deleteConversation(activePlatformId!, conversationIdNumber),
    onSuccess: () => {
      // 软删除只影响列表可见性，主体列表的会话数也要跟着刷新。
      void queryClient.invalidateQueries({
        queryKey: ['conversation-principals'],
      })
      toast.success('已移除会话，消息与用量记录仍保留')
      setConfirmOpen(false)
      void navigate({
        to: '/conversations',
        search: { platform: activePlatformId },
      })
    },
    onError: () => toast.error('移除失败，请稍后重试'),
  })

  const detail = detailQuery.data
  const usage = detail?.usage
  const isDeleted = detail?.status === 'deleted'

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
            <div className='text-muted-foreground mb-2 flex flex-wrap items-center gap-2 text-xs'>
              <Link
                to='/conversations'
                search={{ platform: activePlatformId }}
                className='hover:underline'
              >
                会话记录
              </Link>
              <span>/</span>
              {detail ? (
                <>
                  <span>{PRINCIPAL_TYPE_TEXT[detail.principal_type]}</span>
                  <span>/</span>
                  <Link
                    to='/conversations/$principalType/$principalId'
                    params={{
                      principalType: detail.principal_type,
                      principalId: String(detail.principal_id),
                    }}
                    search={{
                      platform: activePlatformId,
                      name: detail.principal_name ?? undefined,
                    }}
                    className='hover:underline'
                  >
                    {detail.principal_name ?? `#${detail.principal_id}`}
                  </Link>
                </>
              ) : (
                <span>会话 #{conversationId}</span>
              )}
            </div>
            <h2 className='flex items-center gap-2 text-2xl font-bold tracking-tight'>
              {detailQuery.isLoading
                ? `会话 #${conversationId}`
                : (detail?.title ?? `会话 #${conversationId}`)}
              {detail && (
                <Badge variant={isDeleted ? 'secondary' : 'outline'}>
                  {STATUS_TEXT[detail.status] ?? detail.status}
                </Badge>
              )}
            </h2>
            <p className='text-muted-foreground'>
              {detail
                ? `${detail.agent_name ?? '未知 Agent'} · ${detail.message_count} 条消息 · 创建于 ${formatDateTime(detail.created_at)}`
                : '会话详情'}
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <PlatformPicker
              value={activePlatformId}
              platforms={platforms}
              onChange={setPlatformId}
            />
            <Button variant='outline' size='sm' asChild>
              <Link
                to='/conversations'
                search={{ platform: activePlatformId }}
              >
                <ArrowLeft className='size-4' />
                返回会话列表
              </Link>
            </Button>
            <Button
              variant='destructive'
              size='sm'
              disabled={isDeleted || !enabled}
              onClick={() => setConfirmOpen(true)}
            >
              <Trash2 className='size-4' />
              移除会话
            </Button>
          </div>
        </div>

        {platformsLoading ? (
          <Skeleton className='h-64 w-full' />
        ) : activePlatformId == null ? (
          <p className='text-muted-foreground text-sm'>没有可用平台。</p>
        ) : detailQuery.isError ? (
          <p className='text-destructive text-sm'>
            未找到该会话，或当前账号不是该平台的管理员。
          </p>
        ) : (
          <>
            <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-4'>
              <StatItem label='消息数' value={detail?.message_count ?? '-'} />
              <StatItem
                label='输入 token'
                value={usage?.prompt_tokens ?? '-'}
              />
              <StatItem
                label='输出 token'
                value={usage?.completion_tokens ?? '-'}
              />
              <StatItem
                label='合计 token'
                value={usage?.total_tokens ?? '-'}
              />
            </div>

            <Card>
              <CardContent className='flex flex-col gap-3 p-4'>
                <div className='flex flex-wrap items-center justify-between gap-2'>
                  <div className='text-muted-foreground text-sm'>
                    最近消息 {formatDateTime(detail?.last_message_at)} · 用量记录{' '}
                    {usage?.record_count ?? 0} 条
                  </div>
                  <label className='text-muted-foreground flex items-center gap-2 text-sm'>
                    <Switch
                      checked={showAgentLoop}
                      onCheckedChange={setShowAgentLoop}
                    />
                    显示 Agent 执行过程
                  </label>
                </div>
                <ConversationHistoryIsland
                  platformId={activePlatformId}
                  conversationId={conversationIdNumber}
                  showAgentLoop={showAgentLoop}
                  emptyText='该会话还没有消息'
                />
              </CardContent>
            </Card>
          </>
        )}
      </Main>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title='移除会话'
        desc='移除后该会话不再出现在默认列表中，但消息与模型用量记录会保留，仍可用「仅已删除」筛出来。'
        confirmText='移除'
        destructive
        isLoading={deleteMutation.isPending}
        handleConfirm={() => deleteMutation.mutate()}
      />
    </>
  )
}
