import { useQuery } from '@tanstack/react-query'
import { getRouteApi } from '@tanstack/react-router'
import { ArrowLeft, Boxes } from 'lucide-react'
import { getAgent } from '@/api/agent'
import { listPlatforms } from '@/api/platform'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { ThemeSwitch } from '@/components/theme-switch'
import { AgentConfigTab } from './agent-config-tab'
import { AgentKnowledgeTab } from './agent-knowledge-tab'
import { AgentOverviewTab } from './agent-overview-tab'
import { AgentSkillsTab } from './agent-skills-tab'
import { AgentToolsTab } from './agent-tools-tab'
import { AgentUsageTab } from './agent-usage-tab'
import { AgentVersionsTab } from './agent-versions-tab'

export type AgentTabKey =
  | 'overview'
  | 'config'
  | 'knowledge'
  | 'skills'
  | 'tools'
  | 'versions'
  | 'usage'

const routeApi = getRouteApi('/_authenticated/ai/bots/$agentId')

export function AgentDetailPage() {
  const { agentId } = routeApi.useParams()
  const search = routeApi.useSearch()
  const navigate = routeApi.useNavigate()
  const platformsQuery = useQuery({
    queryKey: ['platforms'],
    queryFn: listPlatforms,
  })
  const platformId = search.platform ?? platformsQuery.data?.[0]?.id
  const agentIdNumber = Number(agentId)
  const tab = search.tab ?? 'overview'
  const agentQuery = useQuery({
    queryKey: ['agent', platformId, agentIdNumber],
    queryFn: () => getAgent(platformId!, agentIdNumber),
    enabled: platformId != null,
  })
  const agent = agentQuery.data
  const currentVersion = agent?.current_version

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
        <Button
          variant='ghost'
          size='sm'
          className='w-fit'
          onClick={() =>
            navigate({ to: '/ai/bots', search: { platform: platformId } })
          }
        >
          <ArrowLeft className='size-4' />
          智能体列表
        </Button>
        <div className='flex flex-wrap items-start justify-between gap-3'>
          <div className='flex items-center gap-3'>
            <div className='flex size-11 items-center justify-center rounded-md bg-muted'>
              <Boxes className='size-5 text-muted-foreground' />
            </div>
            <div>
              <div className='flex flex-wrap items-center gap-2'>
                <h2 className='text-2xl font-bold tracking-tight'>
                  {agentQuery.isLoading ? (
                    <Skeleton className='h-7 w-40' />
                  ) : (
                    (agent?.name ?? '智能体')
                  )}
                </h2>
                {agent && (
                  <Badge variant={agent.is_active ? 'default' : 'secondary'}>
                    {agent.is_active ? '启用' : '停用'}
                  </Badge>
                )}
              </div>
              <div className='mt-1 text-sm text-muted-foreground'>
                {agent ? `${agent.slug} · 当前配置实时生效` : ''}
              </div>
            </div>
          </div>
          <div className='text-sm text-muted-foreground'>
            {currentVersion ? (
              <>
                当前版本{' '}
                <span className='font-medium text-foreground'>
                  v{currentVersion.version}
                </span>
                <span className='mx-2'>·</span>
                {currentVersion.model_name}
              </>
            ) : agent ? (
              '尚未发布版本'
            ) : null}
          </div>
        </div>
        {agentQuery.isError && (
          <div className='flex min-h-24 flex-col items-center justify-center gap-3 rounded-md border border-dashed p-6 text-center'>
            <p className='text-sm text-muted-foreground'>智能体加载失败</p>
            <Button
              size='sm'
              variant='outline'
              onClick={() => agentQuery.refetch()}
              disabled={agentQuery.isFetching}
            >
              重试
            </Button>
          </div>
        )}
        <Tabs
          value={tab}
          onValueChange={(value) =>
            navigate({
              search: { platform: platformId, tab: value as AgentTabKey },
            })
          }
          className='gap-0'
        >
          <TabsList className='h-auto w-full justify-start overflow-x-auto rounded-lg mb-4'>
            <TabsTrigger value='overview'>概览</TabsTrigger>
            <TabsTrigger value='config'>配置</TabsTrigger>
            <TabsTrigger value='knowledge'>知识库</TabsTrigger>
            <TabsTrigger value='skills'>技能</TabsTrigger>
            <TabsTrigger value='tools'>工具</TabsTrigger>
            <TabsTrigger value='versions'>版本</TabsTrigger>
            <TabsTrigger value='usage'>用量</TabsTrigger>
          </TabsList>
          <TabsContent value='overview'>
            <AgentOverviewTab platformId={platformId} agentId={agentIdNumber} />
          </TabsContent>
          <TabsContent value='config'>
            <AgentConfigTab platformId={platformId} agentId={agentIdNumber} />
          </TabsContent>
          <TabsContent value='knowledge'>
            <AgentKnowledgeTab
              platformId={platformId}
              agentId={agentIdNumber}
            />
          </TabsContent>
          <TabsContent value='skills'>
            <AgentSkillsTab platformId={platformId} agentId={agentIdNumber} />
          </TabsContent>
          <TabsContent value='tools'>
            <AgentToolsTab platformId={platformId} agentId={agentIdNumber} />
          </TabsContent>
          <TabsContent value='versions'>
            <AgentVersionsTab platformId={platformId} agentId={agentIdNumber} />
          </TabsContent>
          <TabsContent value='usage'>
            <AgentUsageTab platformId={platformId} agentId={agentIdNumber} />
          </TabsContent>
        </Tabs>
      </Main>
    </>
  )
}
