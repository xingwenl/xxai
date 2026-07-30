import { createFileRoute } from '@tanstack/react-router'
import { McpServersPage } from '@/features/system/mcp-servers'

export const Route = createFileRoute('/_authenticated/system/mcp-servers')({
  component: McpServersRoute,
})

function McpServersRoute() {
  return <McpServersPage />
}
