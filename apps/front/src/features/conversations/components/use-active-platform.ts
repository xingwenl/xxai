import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listPlatforms } from '@/api/platform'

/**
 * 平台选择状态：URL 带进来的平台优先，其次用户手选，最后回退到第一个平台。
 *
 * 与任务、模型用量页保持一致——从「执行记录 → 查看会话」这类外部入口进来时，链接会把
 * platform 一起带上；直接打开页面时按第一个平台展示。
 */
export function useActivePlatform(initialPlatformId?: number) {
  const [platformId, setPlatformId] = useState<number | undefined>(
    initialPlatformId
  )
  const platformsQuery = useQuery({
    queryKey: ['platforms'],
    queryFn: listPlatforms,
  })

  return {
    activePlatformId:
      platformId ?? initialPlatformId ?? platformsQuery.data?.[0]?.id,
    setPlatformId,
    platforms: platformsQuery.data ?? [],
    isLoading: platformsQuery.isLoading,
  }
}
