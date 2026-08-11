import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ExternalLink } from 'lucide-react'
import { Bar, BarChart, ResponsiveContainer, XAxis, YAxis } from 'recharts'
import { getModelUsageSummary, listModelUsage } from '@/api/model-usage'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  formatNumber,
  getUsageRanges,
  percentChange,
} from './agent-usage-utils'

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

export function AgentUsageTab({
  platformId,
  agentId,
}: {
  platformId?: number
  agentId: number
}) {
  const [rangeDays, setRangeDays] = useState<7 | 30>(7)
  const ranges = useMemo(() => getUsageRanges(rangeDays), [rangeDays])
  const enabled = platformId != null
  const currentQuery = useQuery({
    queryKey: [
      'agent-usage-summary',
      platformId,
      agentId,
      ranges.start,
      ranges.end,
    ],
    queryFn: () =>
      getModelUsageSummary(platformId!, {
        agent_id: agentId,
        start_date: ranges.start,
        end_date: ranges.end,
      }),
    enabled,
  })
  const previousQuery = useQuery({
    queryKey: [
      'agent-usage-summary',
      platformId,
      agentId,
      ranges.previousStart,
      ranges.previousEnd,
    ],
    queryFn: () =>
      getModelUsageSummary(platformId!, {
        agent_id: agentId,
        start_date: ranges.previousStart,
        end_date: ranges.previousEnd,
      }),
    enabled,
  })
  const recordsQuery = useQuery({
    queryKey: [
      'agent-usage-records',
      platformId,
      agentId,
      ranges.start,
      ranges.end,
    ],
    queryFn: () =>
      listModelUsage(platformId!, {
        agent_id: agentId,
        start_date: ranges.start,
        end_date: ranges.end,
        page: 1,
        page_size: 10,
      }),
    enabled,
  })
  const totals = currentQuery.data?.totals
  const previous = previousQuery.data?.totals
  const trend = (currentQuery.data?.by_day ?? []).map((row) => ({
    day: row.day,
    total: row.total_tokens,
  }))
  const metrics = [
    {
      label: '调用次数',
      value: totals?.record_count ?? 0,
      previous: previous?.record_count ?? 0,
    },
    {
      label: '输入 token',
      value: totals?.prompt_tokens ?? 0,
      previous: previous?.prompt_tokens ?? 0,
    },
    {
      label: '输出 token',
      value: totals?.completion_tokens ?? 0,
      previous: previous?.completion_tokens ?? 0,
    },
    {
      label: '总 token',
      value: totals?.total_tokens ?? 0,
      previous: previous?.total_tokens ?? 0,
    },
  ]

  return (
    <div className='grid gap-4'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <div className='flex gap-1'>
          {([7, 30] as const).map((days) => (
            <Button
              key={days}
              size='sm'
              variant={rangeDays === days ? 'default' : 'outline'}
              onClick={() => setRangeDays(days)}
            >
              近 {days} 天
            </Button>
          ))}
        </div>
        <Button asChild variant='outline' size='sm'>
          <Link
            to='/ai/model-usage'
            search={{ platform: platformId, agent: agentId }}
          >
            查看完整用量
            <ExternalLink className='ms-2 size-4' />
          </Link>
        </Button>
      </div>

      <div className='grid gap-3 md:grid-cols-4'>
        {metrics.map((metric) => {
          const change =
            metric.previous > 0
              ? percentChange(metric.value, metric.previous)
              : null
          return (
            <Card key={metric.label} className='rounded-md py-4'>
              <CardHeader className='gap-2 px-4 pb-0'>
                <CardTitle className='text-xs font-medium tracking-wide text-muted-foreground'>
                  {metric.label}
                </CardTitle>
              </CardHeader>
              <CardContent className='px-4 pt-2'>
                <div className='text-2xl font-semibold tabular-nums'>
                  {currentQuery.isLoading ? (
                    <Skeleton className='h-8 w-24' />
                  ) : (
                    formatNumber(metric.value)
                  )}
                </div>
                <div className='mt-1 text-xs text-muted-foreground'>
                  {change ? `较上一周期 ${change}` : '暂无对比'}
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      <Card className='rounded-md py-0'>
        <CardHeader className='border-b px-4 py-4'>
          <CardTitle className='text-base'>Token 趋势</CardTitle>
        </CardHeader>
        <CardContent className='px-2 pt-4'>
          {trend.length ? (
            <ResponsiveContainer width='100%' height={220}>
              <BarChart data={trend}>
                <XAxis
                  dataKey='day'
                  stroke='#888888'
                  fontSize={12}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  stroke='#888888'
                  fontSize={12}
                  tickLine={false}
                  axisLine={false}
                  width={56}
                />
                <Bar
                  dataKey='total'
                  fill='currentColor'
                  radius={[4, 4, 0, 0]}
                  className='fill-primary'
                />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className='flex h-44 items-center justify-center text-sm text-muted-foreground'>
              {currentQuery.isLoading ? '加载中...' : '当前范围没有用量数据'}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className='rounded-md py-0'>
        <CardHeader className='border-b px-4 py-4'>
          <CardTitle className='text-base'>最近调用</CardTitle>
        </CardHeader>
        <CardContent className='px-0'>
          <div className='overflow-x-auto'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>时间</TableHead>
                  <TableHead>会话</TableHead>
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
                      <TableCell colSpan={7}>
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
                      <TableCell>会话 #{record.conversation_id}</TableCell>
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
                    <TableCell colSpan={7}>
                      <div className='flex h-28 items-center justify-center text-sm text-muted-foreground'>
                        当前范围没有用量明细
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
