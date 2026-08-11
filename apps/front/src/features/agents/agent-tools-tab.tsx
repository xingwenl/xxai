import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { BuiltinToolsSection } from './builtin-tools-section'
import { HostToolsSection } from './host-tools-section'
import { McpToolsSection } from './mcp-tools-section'

export function AgentToolsTab({
  platformId,
  agentId,
}: {
  platformId?: number
  agentId: number
}) {
  return (
    <Tabs defaultValue='builtin' className='gap-0'>
      <TabsList className='w-fit'>
        <TabsTrigger value='builtin'>内置工具</TabsTrigger>
        <TabsTrigger value='mcp'>MCP 工具</TabsTrigger>
        <TabsTrigger value='host'>宿主工具</TabsTrigger>
      </TabsList>
      <TabsContent value='builtin'>
        <BuiltinToolsSection platformId={platformId} agentId={agentId} />
      </TabsContent>
      <TabsContent value='mcp'>
        <McpToolsSection platformId={platformId} agentId={agentId} />
      </TabsContent>
      <TabsContent value='host'>
        <HostToolsSection platformId={platformId} agentId={agentId} />
      </TabsContent>
    </Tabs>
  )
}
