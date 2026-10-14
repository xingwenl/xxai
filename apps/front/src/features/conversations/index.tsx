import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { MessagesSquare, RefreshCw, Search } from 'lucide-react'
import { listAgents } from '@/api/agent'
import {
  listConversationPrincipals,
  type ConversationPrincipalType,
  type ConsoleConversationQuery,
} from '@/api/conversation'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { ThemeSwitch } from '@/components/theme-switch'
import { formatDateTime } from '@/lib/time'
import { ConversationListIsland } from './components/conversation-list-island'
import { PlatformPicker } from './components/platform-picker'
import { useActivePlatform } from './components/use-active-platform'

const PAGE_SIZE = 20

const PRINCIPAL_TYPE_TEXT: Record<ConversationPrincipalType, string> = {
  user: '后台用户',
  end_user: '终端用户',
}

/** 会话状态筛选项：默认只看正常会话，需要时再翻出软删除的。 */
const CONVERSATION_STATUS_OPTIONS = [
  { value: 'active', label: '正常会话' },
  { value: 'deleted', label: '仅已删除' },
  { value: 'all', label: '全部（含已删除）' },
]

/**
 * 会话记录第一层：平台 + 会话主体，以及「全部会话」的整体视图。
 *
 * 数据全部来自 `conversations` / `conversation_messages` / `model_usage_records`，
 * 与终端用户侧 embed 接口共用同一份投影（见 docs/adr/0003-conversation-history-read-boundary.md）。
 */
export function ConversationsPage({
  initialPlatformId,
}: {
  initialPlatformId?: number
} = {}) {
  const {
    activePlatformId,
    setPlatformId,
    platforms,
    isLoading: platformsLoading,
  } = useActivePlatform(initialPlatformId)
  const navigate = useNavigate()

  const [tab, setTab] = useState('principals')

  // 第一层「会话主体」的筛选状态。
  const [page, setPage] = useState(1)
  const [principalType, setPrincipalType] = useState<
    'all' | ConversationPrincipalType
  >('all')
  const [keywordInput, setKeywordInput] = useState('')
  const [keyword, setKeyword] = useState('')
  const [includeDeleted, setIncludeDeleted] = useState(false)

  // 第一层「全部会话」的筛选状态；分页由 SDK 列表组件自己维护。
  const [agentId, setAgentId] = useState('all')
  const [convStatus, setConvStatus] = useState('active')
  const [convKeywordInput, setConvKeywordInput] = useState('')
  const [convKeyword, setConvKeyword] = useState('')

  const principalsQuery = useQuery({
    queryKey: [
      'conversation-principals',
      activePlatformId,
      page,
      principalType,
      keyword,
      includeDeleted,
    ],
    queryFn: () =>
      listConversationPrincipals(activePlatformId!, {
        page,
        pageSize: PAGE_SIZE,
        principal_type: principalType === 'all' ? undefined : principalType,
        keyword: keyword || undefined,
        include_deleted: includeDeleted || undefined,
      }),
    enabled: activePlatformId != null,
  })

  const agentsQuery = useQuery({
    queryKey: ['agents', activePlatformId],
    queryFn: () => listAgents(activePlatformId!),
    enabled: activePlatformId != null,
  })

  // SDK 列表依赖的查询参数：只有真正选了值才下发，避免空串被后端当成筛选条件。
  const conversationQuery: ConsoleConversationQuery = {
    page_size: PAGE_SIZE,
    ...(agentId !== 'all' ? { agent_id: Number(agentId) } : {}),
    ...(convStatus === 'deleted' ? { status: 'deleted' } : {}),
    ...(convStatus === 'all' ? { include_deleted: true } : {}),
    ...(convKeyword ? { keyword: convKeyword } : {}),
  }

  const principals = principalsQuery.data?.items ?? []
  const totalPage = principalsQuery.data?.totalPage ?? 1

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
            <div className='mb-2 flex items-center gap-2 text-xs font-medium tracking-[0.14em] text-muted-foreground uppercase'>
              <MessagesSquare className='size-4' />
              AI 管理 / 会话记录
            </div>
            <h2 className='text-2xl font-bold tracking-tight'>会话记录</h2>
            <p className='text-muted-foreground'>
              按会话主体查看每个用户与 Agent 的历史对话，可下钻到单条会话的完整消息与
              Agent 执行过程。
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <PlatformPicker
              value={activePlatformId}
              platforms={platforms}
              onChange={(next) => {
                setPlatformId(next)
                setPage(1)
                setAgentId('all')
              }}
            />
            <Button
              variant='outline'
              size='sm'
              onClick={() => void principalsQuery.refetch()}
              disabled={activePlatformId == null || principalsQuery.isFetching}
            >
              <RefreshCw className='size-4' />
              刷新
            </Button>
          </div>
        </div>

        {platformsLoading ? (
          <Skeleton className='h-64 w-full' />
        ) : activePlatformId == null ? (
          <p className='text-muted-foreground text-sm'>
            还没有可用平台，请先在「平台管理」里创建平台。
          </p>
        ) : (
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList>
              <TabsTrigger value='principals'>会话主体</TabsTrigger>
              <TabsTrigger value='all'>全部会话</TabsTrigger>
            </TabsList>

            <TabsContent value='principals' className='mt-4'>
              <Card>
                <CardContent className='flex flex-col gap-4 p-4'>
                  <div className='flex flex-wrap items-end gap-2'>
                    <div className='min-w-40'>
                      <div className='text-muted-foreground mb-1 text-xs font-medium'>
                        主体类型
                      </div>
                      <Select
                        value={principalType}
                        onValueChange={(next) => {
                          setPrincipalType(
                            next as 'all' | ConversationPrincipalType
                          )
                          setPage(1)
                        }}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value='all'>全部类型</SelectItem>
                          <SelectItem value='user'>后台用户</SelectItem>
                          <SelectItem value='end_user'>终端用户</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className='min-w-48 flex-1'>
                      <div className='text-muted-foreground mb-1 text-xs font-medium'>
                        主体名称
                      </div>
                      <Input
                        value={keywordInput}
                        placeholder='按名称/外部标识搜索'
                        onChange={(event) => setKeywordInput(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') {
                            setKeyword(keywordInput.trim())
                            setPage(1)
                          }
                        }}
                      />
                    </div>
                    <Button
                      variant='outline'
                      onClick={() => {
                        setKeyword(keywordInput.trim())
                        setPage(1)
                      }}
                    >
                      <Search className='size-4' />
                      查询
                    </Button>
                    <label className='text-muted-foreground flex items-center gap-2 text-sm'>
                      <Checkbox
                        checked={includeDeleted}
                        onCheckedChange={(checked) => {
                          setIncludeDeleted(checked === true)
                          setPage(1)
                        }}
                      />
                      包含已删除会话
                    </label>
                  </div>

                  <div className='rounded-md border'>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>会话主体</TableHead>
                          <TableHead>类型</TableHead>
                          <TableHead className='text-end'>会话数</TableHead>
                          <TableHead>最近会话</TableHead>
                          <TableHead className='text-end'>操作</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {principalsQuery.isLoading ? (
                          <TableRow>
                            <TableCell
                              colSpan={5}
                              className='text-muted-foreground h-24 text-center'
                            >
                              加载中...
                            </TableCell>
                          </TableRow>
                        ) : principals.length === 0 ? (
                          <TableRow>
                            <TableCell
                              colSpan={5}
                              className='text-muted-foreground h-24 text-center'
                            >
                              暂无会话主体
                            </TableCell>
                          </TableRow>
                        ) : (
                          principals.map((principal) => (
                            <TableRow
                              key={`${principal.principal_type}-${principal.principal_id}`}
                            >
                              <TableCell className='font-medium'>
                                <Link
                                  to='/conversations/$principalType/$principalId'
                                  params={{
                                    principalType: principal.principal_type,
                                    principalId: String(principal.principal_id),
                                  }}
                                  search={{
                                    platform: activePlatformId,
                                    name: principal.display_name ?? undefined,
                                  }}
                                  className='hover:underline'
                                >
                                  {principal.display_name ??
                                    `#${principal.principal_id}`}
                                </Link>
                              </TableCell>
                              <TableCell className='text-muted-foreground'>
                                {PRINCIPAL_TYPE_TEXT[principal.principal_type]}
                              </TableCell>
                              <TableCell className='text-end'>
                                {principal.conversation_count}
                              </TableCell>
                              <TableCell className='text-muted-foreground'>
                                {formatDateTime(principal.last_conversation_at)}
                              </TableCell>
                              <TableCell className='text-end'>
                                <Link
                                  to='/conversations/$principalType/$principalId'
                                  params={{
                                    principalType: principal.principal_type,
                                    principalId: String(principal.principal_id),
                                  }}
                                  search={{
                                    platform: activePlatformId,
                                    name: principal.display_name ?? undefined,
                                  }}
                                  className='text-xs underline'
                                >
                                  查看会话
                                </Link>
                              </TableCell>
                            </TableRow>
                          ))
                        )}
                      </TableBody>
                    </Table>
                  </div>

                  <div className='text-muted-foreground flex items-center justify-between border-t px-1 pt-3 text-sm'>
                    <span>
                      共 {principalsQuery.data?.total ?? 0} 个会话主体，当前第{' '}
                      {page} / {totalPage} 页
                    </span>
                    <div className='flex gap-2'>
                      <Button
                        variant='outline'
                        size='sm'
                        onClick={() => setPage((value) => Math.max(1, value - 1))}
                        disabled={page <= 1 || principalsQuery.isFetching}
                      >
                        上一页
                      </Button>
                      <Button
                        variant='outline'
                        size='sm'
                        onClick={() => setPage((value) => value + 1)}
                        disabled={
                          principalsQuery.isFetching || page >= totalPage
                        }
                      >
                        下一页
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value='all' className='mt-4'>
              <Card>
                <CardContent className='flex flex-col gap-4 p-4'>
                  <div className='flex flex-wrap items-end gap-2'>
                    <div className='min-w-40'>
                      <div className='text-muted-foreground mb-1 text-xs font-medium'>
                        会话状态
                      </div>
                      <Select
                        value={convStatus}
                        onValueChange={setConvStatus}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {CONVERSATION_STATUS_OPTIONS.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                              {option.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className='min-w-40'>
                      <div className='text-muted-foreground mb-1 text-xs font-medium'>
                        Agent
                      </div>
                      <Select value={agentId} onValueChange={setAgentId}>
                        <SelectTrigger>
                          <SelectValue placeholder='全部 Agent' />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value='all'>全部 Agent</SelectItem>
                          {(agentsQuery.data?.items ?? []).map((agent) => (
                            <SelectItem
                              key={agent.id}
                              value={agent.id.toString()}
                            >
                              {agent.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className='min-w-48 flex-1'>
                      <div className='text-muted-foreground mb-1 text-xs font-medium'>
                        标题或消息摘要
                      </div>
                      <Input
                        value={convKeywordInput}
                        placeholder='按标题/末条消息搜索'
                        onChange={(event) =>
                          setConvKeywordInput(event.target.value)
                        }
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') {
                            setConvKeyword(convKeywordInput.trim())
                          }
                        }}
                      />
                    </div>
                    <Button
                      variant='outline'
                      onClick={() => setConvKeyword(convKeywordInput.trim())}
                    >
                      <Search className='size-4' />
                      查询
                    </Button>
                  </div>

                  <ConversationListIsland
                    platformId={activePlatformId}
                    query={conversationQuery}
                    emptyText='暂无会话'
                    onSelect={(conversation) =>
                      void navigate({
                        to: '/conversations/$conversationId',
                        params: { conversationId: String(conversation.id) },
                        search: { platform: activePlatformId },
                      })
                    }
                  />
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        )}
      </Main>
    </>
  )
}
