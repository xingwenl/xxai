import { useEffect, useMemo, useRef } from 'react'
import { ConversationList, type ConversationSummaryPayload } from 'xxai-agent'
import {
  createConversationHistorySource,
  type ConsoleConversationQuery,
} from '@/api/conversation'
import { VueIsland } from './vue-island'

/**
 * 会话列表岛：把 ai-sdk 的 ConversationList 挂进 React 页面。
 *
 * 数据源由本仓库 api 层提供（平台隔离与 token 都在那边），SDK 只负责渲染与翻页。
 */
export function ConversationListIsland({
  platformId,
  query,
  emptyText,
  onSelect,
}: {
  platformId: number
  query?: ConsoleConversationQuery
  emptyText?: string
  onSelect?: (conversation: ConversationSummaryPayload) => void
}) {
  const source = useMemo(
    () => createConversationHistorySource(platformId),
    [platformId]
  )
  // 回调走 ref：岛重建时重新读取最新实现，避免把旧筛选条件闭包带进组件。
  // React Compiler 不允许在渲染期写 ref，因此在 effect 里同步。
  const selectRef = useRef(onSelect)
  useEffect(() => {
    selectRef.current = onSelect
  })

  return (
    <VueIsland
      component={ConversationList}
      depKey={`${platformId}|${JSON.stringify(query ?? {})}`}
      className='min-h-[16rem]'
      props={{
        source,
        params: query,
        emptyText,
        onSelect: (conversation: ConversationSummaryPayload) =>
          selectRef.current?.(conversation),
      }}
    />
  )
}
