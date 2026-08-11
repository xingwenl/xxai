import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart3, CalendarDays, RefreshCw, Users } from 'lucide-react'
import { listAgents } from '@/api/agent'
import { listEmbedClients } from '@/api/embed-clients'
import {
  getModelUsageSummary,
  listModelUsage,
  type ModelUsageQuery,
} from '@/api/model-usage'
import { listPlatforms } from '@/api/platform'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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

const DAY_MS = 24 * 60 * 60 * 1000

function toDateInput(value: Date) {
  return value.toISOString().slice(0, 10)
}

function getDefaultDateRange() {
  const end = new Date()
  const start = new Date(end.getTime() - 6 * DAY_MS)
  return {
    start: toDateInput(start),
    end: toDateInput(end),
  }
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value)
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function SummaryTable({
  rows,
  kind,
}: {
  rows:
    | Array<{
        record_count: number
        prompt_tokens: number
        completion_tokens: number
        total_tokens: number
        agent_id?: number
        agent_name?: string
        client_id?: string | null
        client_name?: string | null
        day?: string
      }>
    | undefined
  kind: 'agent' | 'client' | 'day'
}) {
  if (!rows?.length) {
    return (
      <div className='flex h-32 items-center justify-center text-sm text-muted-foreground'>
        当前筛选范围没有汇总数据
      </div>
    )
  }
  return (
    <div className='overflow-x-auto'>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>
              {kind === 'agent'
                ? 'Agent'
                : kind === 'client'
                  ? 'Client'
                  : '日期'}
            </TableHead>
            <TableHead className='text-end'>记录数</TableHead>
            <TableHead className='text-end'>输入</TableHead>
            <TableHead className='text-end'>输出</TableHead>
            <TableHead className='text-end'>总 token</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const label =
              kind === 'agent'
                ? row.agent_name
                : kind === 'client'
                  ? row.client_name || row.client_id || '后台会话'
                  : row.day
            return (
              <TableRow key={`${kind}-${label}`}>
                <TableCell className='font-medium'>{label}</TableCell>
                <TableCell className='text-end'>
                  {formatNumber(row.record_count)}
                </TableCell>
                <TableCell className='text-end'>
                  {formatNumber(row.prompt_tokens)}
                </TableCell>
                <TableCell className='text-end'>
                  {formatNumber(row.completion_tokens)}
                </TableCell>
                <TableCell className='text-end font-semibold'>
                  {formatNumber(row.total_tokens)}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}

export function ModelUsagePage({
  initialPlatformId,
  initialAgentId,
}: {
  initialPlatformId?: number
  initialAgentId?: string
} = {}) {
  const defaultRange = useMemo(() => getDefaultDateRange(), [])
  const [platformId, setPlatformId] = useState<number | undefined>(
    initialPlatformId
  )
  const [agentId, setAgentId] = useState<string>(initialAgentId ?? 'all')
  const [clientId, setClientId] = useState<string>('all')
  const [startDate, setStartDate] = useState(defaultRange.start)
  const [endDate, setEndDate] = useState(defaultRange.end)
  const [page, setPage] = useState(1)
  const [tab, setTab] = useState('agent')

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
  const clientsQuery = useQuery({
    queryKey: ['embed-clients', activePlatformId],
    queryFn: () => listEmbedClients(activePlatformId!),
    enabled: activePlatformId != null,
  })

  const query = useMemo<ModelUsageQuery>(
    () => ({
      start_date: startDate,
      end_date: endDate,
      ...(agentId !== 'all' ? { agent_id: Number(agentId) } : {}),
      ...(clientId !== 'all' ? { client_id: clientId } : {}),
      page,
      page_size: 20,
    }),
    [agentId, clientId, endDate, page, startDate]
  )
  const queryEnabled =
    activePlatformId != null &&
    startDate.length > 0 &&
    endDate.length > 0 &&
    startDate <= endDate
  const summaryQuery = useQuery({
    queryKey: ['model-usage-summary', activePlatformId, query],
    queryFn: () => getModelUsageSummary(activePlatformId!, query),
    enabled: queryEnabled,
  })
  const recordsQuery = useQuery({
    queryKey: ['model-usage-records', activePlatformId, query],
    queryFn: () => listModelUsage(activePlatformId!, query),
    enabled: queryEnabled,
  })

  const selectedPlatform = platformsQuery.data?.find(
    (platform) => platform.id === activePlatformId
  )
  const totals = summaryQuery.data?.totals

  const updateFilter = (callback: () => void) => {
    callback()
    setPage(1)
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
            <div className='mb-2 flex items-center gap-2 text-xs font-medium tracking-[0.14em] text-muted-foreground uppercase'>
              <BarChart3 className='size-4' />
              AI 管理 / 用量观察
            </div>
            <h2 className='text-2xl font-bold tracking-tight'>模型用量</h2>
            <p className='text-muted-foreground'>
              从总量、分组和明细三个层次查看模型消耗。
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <Select
              value={activePlatformId?.toString()}
              onValueChange={(value) => {
                setPlatformId(Number(value))
                setAgentId('all')
                setClientId('all')
                setPage(1)
              }}
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
              onClick={() => {
                void summaryQuery.refetch()
                void recordsQuery.refetch()
              }}
              disabled={
                !queryEnabled ||
                summaryQuery.isFetching ||
                recordsQuery.isFetching
              }
            >
              <RefreshCw className='size-4' />
              刷新
            </Button>
          </div>
        </div>

        <div className='flex flex-wrap items-end gap-2 rounded-md border bg-muted/20 p-3'>
          <div className='min-w-44'>
            <div className='mb-1 text-xs font-medium text-muted-foreground'>
              Agent
            </div>
            <Select
              value={agentId}
              onValueChange={(value) => updateFilter(() => setAgentId(value))}
              disabled={!activePlatformId}
            >
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
          <div className='min-w-44'>
            <div className='mb-1 text-xs font-medium text-muted-foreground'>
              Embed Client
            </div>
            <Select
              value={clientId}
              onValueChange={(value) => updateFilter(() => setClientId(value))}
              disabled={!activePlatformId}
            >
              <SelectTrigger>
                <SelectValue placeholder='全部 Client' />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value='all'>全部 Client</SelectItem>
                {(clientsQuery.data ?? []).map((client) => (
                  <SelectItem key={client.client_id} value={client.client_id}>
                    {client.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <div className='mb-1 text-xs font-medium text-muted-foreground'>
              开始日期
            </div>
            <Input
              type='date'
              value={startDate}
              onChange={(event) =>
                updateFilter(() => setStartDate(event.target.value))
              }
            />
          </div>
          <div>
            <div className='mb-1 text-xs font-medium text-muted-foreground'>
              结束日期
            </div>
            <Input
              type='date'
              value={endDate}
              onChange={(event) =>
                updateFilter(() => setEndDate(event.target.value))
              }
            />
          </div>
          <Badge
            variant={queryEnabled ? 'secondary' : 'destructive'}
            className='mb-1 h-9 px-3'
          >
            {queryEnabled ? '筛选有效' : '请检查日期范围'}
          </Badge>
        </div>

        <div className='grid gap-3 md:grid-cols-4'>
          {[
            ['记录数', totals?.record_count ?? 0, '条用量记录'],
            ['输入 token', totals?.prompt_tokens ?? 0, 'prompt'],
            ['输出 token', totals?.completion_tokens ?? 0, 'completion'],
            ['总 token', totals?.total_tokens ?? 0, '本次筛选'],
          ].map(([label, value, caption]) => (
            <Card key={label} className='rounded-md py-4'>
              <CardHeader className='gap-2 px-4 pb-0'>
                <CardTitle className='text-xs font-medium tracking-wide text-muted-foreground'>
                  {label}
                </CardTitle>
              </CardHeader>
              <CardContent className='px-4 pt-2'>
                <div className='text-2xl font-semibold tabular-nums'>
                  {summaryQuery.isLoading ? (
                    <Skeleton className='h-8 w-28' />
                  ) : (
                    formatNumber(Number(value))
                  )}
                </div>
                <div className='mt-1 text-xs text-muted-foreground'>
                  {caption}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        <Card className='rounded-md py-0'>
          <CardHeader className='border-b px-4 py-4'>
            <div className='flex items-center justify-between gap-2'>
              <div>
                <CardTitle className='text-base'>汇总分组</CardTitle>
                <div className='mt-1 text-xs text-muted-foreground'>
                  当前平台：{selectedPlatform?.name ?? '未选择平台'}
                </div>
              </div>
              <CalendarDays className='size-5 text-muted-foreground' />
            </div>
          </CardHeader>
          <CardContent className='px-0'>
            <Tabs value={tab} onValueChange={setTab} className='gap-0'>
              <TabsList className='m-4'>
                <TabsTrigger value='agent'>
                  <Users className='size-4' />
                  Agent
                </TabsTrigger>
                <TabsTrigger value='client'>Client</TabsTrigger>
                <TabsTrigger value='day'>日期</TabsTrigger>
              </TabsList>
              <TabsContent value='agent' className='m-0'>
                <SummaryTable rows={summaryQuery.data?.by_agent} kind='agent' />
              </TabsContent>
              <TabsContent value='client' className='m-0'>
                <SummaryTable
                  rows={summaryQuery.data?.by_client}
                  kind='client'
                />
              </TabsContent>
              <TabsContent value='day' className='m-0'>
                <SummaryTable rows={summaryQuery.data?.by_day} kind='day' />
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>

        <Card className='rounded-md py-0'>
          <CardHeader className='border-b px-4 py-4'>
            <CardTitle className='text-base'>用量明细</CardTitle>
          </CardHeader>
          <CardContent className='px-0'>
            <div className='overflow-x-auto'>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>时间</TableHead>
                    <TableHead>Agent</TableHead>
                    <TableHead>Client</TableHead>
                    <TableHead>用户 / 会话</TableHead>
                    <TableHead>请求 ID</TableHead>
                    <TableHead>模型</TableHead>
                    <TableHead className='text-end'>输入</TableHead>
                    <TableHead className='text-end'>输出</TableHead>
                    <TableHead className='text-end'>总 token</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {recordsQuery.isLoading ? (
                    Array.from({ length: 5 }).map((_, index) => (
                      <TableRow key={index}>
                        <TableCell colSpan={9}>
                          <Skeleton className='h-8 w-full' />
                        </TableCell>
                      </TableRow>
                    ))
                  ) : recordsQuery.data?.items.length ? (
                    recordsQuery.data.items.map((record) => (
                      <TableRow key={record.id}>
                        <TableCell className='text-xs whitespace-nowrap text-muted-foreground'>
                          {formatDateTime(record.created_at)}
                        </TableCell>
                        <TableCell className='font-medium'>
                          {record.agent_name}
                        </TableCell>
                        <TableCell>
                          {record.client_name || record.client_id || '后台会话'}
                        </TableCell>
                        <TableCell>
                          <div className='text-sm'>
                            {record.platform_end_user_id
                              ? `用户 #${record.platform_end_user_id}`
                              : '后台用户'}
                          </div>
                          <div className='text-xs text-muted-foreground'>
                            会话 #{record.conversation_id}
                          </div>
                        </TableCell>
                        <TableCell className='max-w-44 truncate font-mono text-xs text-muted-foreground'>
                          {record.request_id || '-'}
                        </TableCell>
                        <TableCell className='font-mono text-xs'>
                          {record.model_name || '-'}
                        </TableCell>
                        <TableCell className='text-end tabular-nums'>
                          {formatNumber(record.prompt_tokens)}
                        </TableCell>
                        <TableCell className='text-end tabular-nums'>
                          {formatNumber(record.completion_tokens)}
                        </TableCell>
                        <TableCell className='text-end font-semibold tabular-nums'>
                          {formatNumber(record.total_tokens)}
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={9}>
                        <div className='flex h-28 items-center justify-center text-sm text-muted-foreground'>
                          当前筛选范围没有用量明细
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
            <div className='flex items-center justify-between border-t px-4 py-3 text-sm text-muted-foreground'>
              <span>
                共 {formatNumber(recordsQuery.data?.total ?? 0)} 条，当前第{' '}
                {recordsQuery.data?.page_no ?? page} 页
              </span>
              <div className='flex gap-2'>
                <Button
                  variant='outline'
                  size='sm'
                  onClick={() => setPage((value) => Math.max(1, value - 1))}
                  disabled={page <= 1 || recordsQuery.isFetching}
                >
                  上一页
                </Button>
                <Button
                  variant='outline'
                  size='sm'
                  onClick={() => setPage((value) => value + 1)}
                  disabled={
                    recordsQuery.isFetching ||
                    page >= (recordsQuery.data?.pages ?? 0)
                  }
                >
                  下一页
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </Main>
    </>
  )
}
