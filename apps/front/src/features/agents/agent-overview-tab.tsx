import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  Cable,
  Database,
  FileCode2,
  Link2,
  Wrench,
} from 'lucide-react'
import { Bar, BarChart, ResponsiveContainer, XAxis, YAxis } from 'recharts'
import { getAgent, listAgentVersions } from '@/api/agent'
import { listAgentBuiltinTools } from '@/api/builtin-tools'
import { listAgentHostTools } from '@/api/host-tools'
import { listAgentKnowledgeBases } from '@/api/knowledge'
import { listMcpBindings } from '@/api/mcp-servers'
import { getModelUsageSummary } from '@/api/model-usage'
import { listAgentSkills } from '@/api/skills'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  formatNumber,
  getUsageRanges,
  percentChange,
} from './agent-usage-utils'

export function AgentOverviewTab({
  platformId,
  agentId,
}: {
  platformId?: number
  agentId: number
}) {
  const enabled = platformId != null
  const agentQuery = useQuery({
    queryKey: ['agent', platformId, agentId],
    queryFn: () => getAgent(platformId!, agentId),
    enabled,
  })
  const versionsQuery = useQuery({
    queryKey: ['agent-versions', platformId, agentId],
    queryFn: () => listAgentVersions(platformId!, agentId),
    enabled,
  })
  const knowledgeQuery = useQuery({
    queryKey: ['agent-knowledge-bindings', platformId, agentId],
    queryFn: () => listAgentKnowledgeBases(platformId!, agentId),
    enabled,
  })
  const skillsQuery = useQuery({
    queryKey: ['agent-skill-bindings', platformId, agentId],
    queryFn: () => listAgentSkills(platformId!, agentId),
    enabled,
  })
  const builtinQuery = useQuery({
    queryKey: ['agent-builtin-tools', platformId, agentId],
    queryFn: () => listAgentBuiltinTools(platformId!, agentId),
    enabled,
  })
  const mcpQuery = useQuery({
    queryKey: ['agent-mcp-bindings', platformId, agentId],
    queryFn: () => listMcpBindings(platformId!, agentId),
    enabled,
  })
  const hostQuery = useQuery({
    queryKey: ['agent-host-tools', platformId, agentId],
    queryFn: () => listAgentHostTools(platformId!, agentId),
    enabled,
  })
  const ranges = useMemo(() => getUsageRanges(7), [])
  const currentUsageQuery = useQuery({
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
  const previousUsageQuery = useQuery({
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

  const agent = agentQuery.data
  const counts = {
    knowledge: knowledgeQuery.data?.length ?? 0,
    skills: skillsQuery.data?.length ?? 0,
    builtin: builtinQuery.data?.filter((tool) => tool.is_enabled).length ?? 0,
    mcp: mcpQuery.data?.length ?? 0,
    host: hostQuery.data?.filter((binding) => binding.is_enabled).length ?? 0,
  }
  const totals = currentUsageQuery.data?.totals
  const previous = previousUsageQuery.data?.totals
  const trend = (currentUsageQuery.data?.by_day ?? []).map((row) => ({
    day: row.day,
    total: row.total_tokens,
  }))
  const recentVersions = (versionsQuery.data ?? []).slice(0, 3)
  const hints: string[] = []
  if (agent && !agent.current_version) {
    hints.push('尚未发布版本，当前对话使用默认模型配置。')
  }
  const capabilityTotal =
    counts.knowledge + counts.skills + counts.builtin + counts.mcp + counts.host
  if (agent && capabilityTotal === 0) {
    hints.push('尚未关联任何知识库、技能或工具。')
  }

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
  const capabilityItems = [
    { label: '知识库', value: counts.knowledge, Icon: Database },
    { label: '技能', value: counts.skills, Icon: FileCode2 },
    { label: '内置工具', value: counts.builtin, Icon: Wrench },
    { label: 'MCP 服务', value: counts.mcp, Icon: Cable },
    { label: '宿主工具', value: counts.host, Icon: Link2 },
  ] as const

  return (
    <div className='grid gap-4'>
      <div className='grid gap-4 md:grid-cols-2'>
        <Card className='rounded-md py-4'>
          <CardHeader className='px-4 pb-0'>
            <CardTitle className='text-xs font-medium tracking-wide text-muted-foreground'>
              运行状态
            </CardTitle>
          </CardHeader>
          <CardContent className='px-4 pt-3 text-sm'>
            {agent ? (
              <div className='space-y-1'>
                <div>
                  状态：{' '}
                  <Badge variant={agent.is_active ? 'default' : 'secondary'}>
                    {agent.is_active ? '启用' : '停用'}
                  </Badge>
                </div>
                <div>
                  当前版本：{' '}
                  {agent.current_version
                    ? `v${agent.current_version.version} · ${agent.current_version.model_name}`
                    : '未发布'}
                </div>
                <div>
                  最近发布：{' '}
                  {agent.current_version?.published_at
                    ? new Date(
                        agent.current_version.published_at
                      ).toLocaleString('zh-CN')
                    : '—'}
                </div>
              </div>
            ) : (
              <Skeleton className='h-16 w-full' />
            )}
          </CardContent>
        </Card>
        <Card className='rounded-md py-4'>
          <CardHeader className='px-4 pb-0'>
            <CardTitle className='text-xs font-medium tracking-wide text-muted-foreground'>
              能力摘要
            </CardTitle>
          </CardHeader>
          <CardContent className='px-4 pt-3'>
            <div className='grid grid-cols-2 gap-2 text-sm sm:grid-cols-5'>
              {capabilityItems.map(({ label, value, Icon }) => (
                <div key={label} className='flex items-center gap-2'>
                  <Icon className='size-4 text-muted-foreground' />
                  <span className='text-muted-foreground'>{label}</span>
                  <span className='font-semibold tabular-nums'>{value}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
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
                  {currentUsageQuery.isLoading ? (
                    <Skeleton className='h-8 w-24' />
                  ) : (
                    formatNumber(metric.value)
                  )}
                </div>
                <div className='mt-1 text-xs text-muted-foreground'>
                  {change ? `较前 7 天 ${change}` : '暂无对比'}
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      <div className='grid gap-4 lg:grid-cols-3'>
        <Card className='rounded-md py-0 lg:col-span-2'>
          <CardHeader className='border-b px-4 py-4'>
            <CardTitle className='text-base'>近 7 天 Token 趋势</CardTitle>
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
                {currentUsageQuery.isLoading
                  ? '加载中...'
                  : '当前范围没有用量数据'}
              </div>
            )}
          </CardContent>
        </Card>
        <Card className='rounded-md py-0'>
          <CardHeader className='border-b px-4 py-4'>
            <CardTitle className='text-base'>最近版本</CardTitle>
          </CardHeader>
          <CardContent className='px-4 pt-3'>
            {recentVersions.length ? (
              <div className='space-y-2 text-sm'>
                {recentVersions.map((version) => (
                  <div
                    key={version.id}
                    className='flex items-center justify-between gap-2'
                  >
                    <span className='font-medium'>v{version.version}</span>
                    <span className='truncate text-muted-foreground'>
                      {version.model_name}
                    </span>
                    <span className='text-xs whitespace-nowrap text-muted-foreground'>
                      {version.published_at
                        ? new Date(version.published_at).toLocaleDateString(
                            'zh-CN'
                          )
                        : '未发布'}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className='flex h-24 items-center justify-center text-sm text-muted-foreground'>
                暂无版本
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {hints.length > 0 && (
        <div className='rounded-md border border-dashed px-4 py-3 text-sm text-muted-foreground'>
          <AlertTriangle className='me-2 inline size-4' />
          {hints.join(' ')}
        </div>
      )}
    </div>
  )
}
