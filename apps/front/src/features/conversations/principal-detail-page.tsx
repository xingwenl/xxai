import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { ArrowLeft, Search } from 'lucide-react'
import { listAgents } from '@/api/agent'
import {
  type ConversationPrincipalType,
  type ConsoleConversationQuery,
} from '@/api/conversation'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { ThemeSwitch } from '@/components/theme-switch'
import { ConversationListIsland } from './components/conversation-list-island'
import { PlatformPicker } from './components/platform-picker'
import { useActivePlatform } from './components/use-active-platform'

const routeApi = getRouteApi(
  '/_authenticated/conversations/$principalType/$principalId'
)

const PAGE_SIZE = 20

const PRINCIPAL_TYPE_TEXT: Record<ConversationPrincipalType, string> = {
  user: '后台用户',
  end_user: '终端用户',
}

/**
 * 会话记录第二层：某个会话主体名下的会话列表。
 *
 * 主体只有两种——后台用户与终端用户，用 `principal_type` + `principal_id` 唯一定位；
 * 页面本身不重新查主体，名称由上一层的链接通过 search 带过来。
 */
export function PrincipalDetailPage() {
  const { principalType, principalId } = routeApi.useParams()
  const search = routeApi.useSearch()
  const navigate = routeApi.useNavigate()
  const {
    activePlatformId,
    setPlatformId,
    platforms,
    isLoading: platformsLoading,
  } = useActivePlatform(search.platform)

  // URL 上的主体类型是自由字符串，收敛成契约里的两种枚举值。
  const principalTypeValue: ConversationPrincipalType =
    principalType === 'user' ? 'user' : 'end_user'
  const principalIdNumber = Number(principalId)

  const [status, setStatus] = useState('active')
  const [agentId, setAgentId] = useState('all')
  const [keywordInput, setKeywordInput] = useState('')
  const [keyword, setKeyword] = useState('')

  const agentsQuery = useQuery({
    queryKey: ['agents', activePlatformId],
    queryFn: () => listAgents(activePlatformId!),
    enabled: activePlatformId != null,
  })

  const conversationQuery: ConsoleConversationQuery = {
    page_size: PAGE_SIZE,
    principal_type: principalTypeValue,
    principal_id: principalIdNumber,
    ...(agentId !== 'all' ? { agent_id: Number(agentId) } : {}),
    ...(status === 'deleted' ? { status: 'deleted' } : {}),
    ...(status === 'all' ? { include_deleted: true } : {}),
    ...(keyword ? { keyword } : {}),
  }

  const displayName = search.name ?? `#${principalId}`

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
            <div className='text-muted-foreground mb-2 flex items-center gap-2 text-xs'>
              <Link
                to='/conversations'
                search={{ platform: activePlatformId }}
                className='hover:underline'
              >
                会话记录
              </Link>
              <span>/</span>
              <span>{PRINCIPAL_TYPE_TEXT[principalTypeValue]}</span>
            </div>
            <h2 className='text-2xl font-bold tracking-tight'>{displayName}</h2>
            <p className='text-muted-foreground'>
              该主体在本平台名下的会话；点开任意会话可查看完整消息与 Agent 执行过程。
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <PlatformPicker
              value={activePlatformId}
              platforms={platforms}
              onChange={(next) => {
                setPlatformId(next)
                setAgentId('all')
              }}
            />
            <Button variant='outline' size='sm' asChild>
              <Link to='/conversations' search={{ platform: activePlatformId }}>
                <ArrowLeft className='size-4' />
                返回主体列表
              </Link>
            </Button>
          </div>
        </div>

        <Card>
          <CardContent className='flex flex-col gap-4 p-4'>
            <div className='flex flex-wrap items-end gap-2'>
              <div className='min-w-40'>
                <div className='text-muted-foreground mb-1 text-xs font-medium'>
                  会话状态
                </div>
                <Select value={status} onValueChange={setStatus}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='active'>正常会话</SelectItem>
                    <SelectItem value='deleted'>仅已删除</SelectItem>
                    <SelectItem value='all'>全部（含已删除）</SelectItem>
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
                      <SelectItem key={agent.id} value={agent.id.toString()}>
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
                  value={keywordInput}
                  placeholder='按标题/末条消息搜索'
                  onChange={(event) => setKeywordInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      setKeyword(keywordInput.trim())
                    }
                  }}
                />
              </div>
              <Button
                variant='outline'
                onClick={() => setKeyword(keywordInput.trim())}
              >
                <Search className='size-4' />
                查询
              </Button>
            </div>

            {platformsLoading ? (
              <p className='text-muted-foreground text-sm'>加载平台中...</p>
            ) : activePlatformId == null ? (
              <p className='text-muted-foreground text-sm'>没有可用平台。</p>
            ) : (
              <ConversationListIsland
                platformId={activePlatformId}
                query={conversationQuery}
                emptyText='该主体暂无会话'
                onSelect={(conversation) =>
                  void navigate({
                    to: '/conversations/$conversationId',
                    params: { conversationId: String(conversation.id) },
                    search: { platform: activePlatformId },
                  })
                }
              />
            )}
          </CardContent>
        </Card>
      </Main>
    </>
  )
}
