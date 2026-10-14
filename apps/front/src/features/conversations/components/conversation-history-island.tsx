import { useMemo } from 'react'
import { ConversationHistory } from 'xxai-agent'
import { createConversationHistorySource } from '@/api/conversation'
import { VueIsland } from './vue-island'

/**
 * 会话正文岛：把 ai-sdk 的 ConversationHistory 挂进 React 页面。
 *
 * 「和 ai-sdk 里看到的一样」由这条链路保证：ConversationHistory 内部复用 ChatMessage，
 * `showAgentLoop` 直接透传成 ChatMessage 的 showAgentSteps，Agent 过程卡片一并呈现。
 */
export function ConversationHistoryIsland({
  platformId,
  conversationId,
  showAgentLoop = true,
  emptyText,
}: {
  platformId: number
  conversationId: number
  showAgentLoop?: boolean
  emptyText?: string
}) {
  const source = useMemo(
    () => createConversationHistorySource(platformId),
    [platformId]
  )

  return (
    <VueIsland
      component={ConversationHistory}
      depKey={`${platformId}|${conversationId}|${showAgentLoop}`}
      className='min-h-[24rem]'
      props={{ source, conversationId, showAgentLoop, emptyText }}
    />
  )
}
