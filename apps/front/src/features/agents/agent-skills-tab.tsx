export function AgentSkillsTab({
  platformId,
  agentId,
}: {
  platformId?: number
  agentId: number
}) {
  return (
    <div className='rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground'>
      技能标签页开发中（智能体 {agentId}，平台 {platformId ?? '未选择'}）
    </div>
  )
}
