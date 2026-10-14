import { http } from '@/lib/http'
import type {
  ConversationHistorySource,
  ConversationListParams,
  ConversationMessagePayload,
  ConversationSummaryPayload,
} from 'xxai-agent'

/** 会话主体类型：`user` 是后台用户（sys_users），`end_user` 是终端用户（platform_end_users）。 */
export type ConversationPrincipalType = 'user' | 'end_user'

/** 会话主体聚合项：只有真的产生过会话的主体才会出现在这里。 */
export type ConversationPrincipal = {
  principal_type: ConversationPrincipalType
  principal_id: number
  /** 后台用户取姓名；终端用户优先 display_name，缺失时回退 external_user_id。 */
  display_name: string | null
  conversation_count: number
  last_conversation_at: string | null
}

export type ConversationPrincipalPage = {
  items: ConversationPrincipal[]
  total: number
  page: number
  pageSize: number
  totalPage: number
}

/** 会话级模型用量汇总，直接来自 model_usage_records。 */
export type ConversationUsage = {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  record_count: number
}

export type ConsoleConversation = ConversationSummaryPayload

export type ConsoleConversationDetail = ConsoleConversation & {
  usage: ConversationUsage
}

/**
 * 后台列表查询参数：SDK 的通用参数 + 后台专有的日期区间与「包含已删除」。
 * 字段名与后端 Query 参数逐字一致，避免在 api 层再做一次翻译。
 */
export type ConsoleConversationQuery = ConversationListParams & {
  start_date?: string
  end_date?: string
  include_deleted?: boolean
}

export type ConversationPrincipalQuery = {
  page?: number
  pageSize?: number
  principal_type?: ConversationPrincipalType
  keyword?: string
  include_deleted?: boolean
}

/** 后端分页信封（与冻结契约一致：page / page_size，不是 page_no / pages）。 */
type BackendPage<T> = {
  items?: T[]
  total?: number
  page?: number
  page_size?: number
}

function toPage<T>(data: BackendPage<T> | null | undefined, fallbackSize = 20) {
  const items = data?.items ?? []
  const pageSize = Number(data?.page_size ?? fallbackSize) || fallbackSize
  const total = Number(data?.total ?? 0)
  return {
    items,
    total,
    page: Number(data?.page ?? 1),
    pageSize,
    totalPage: Math.max(1, Math.ceil(total / pageSize)),
  }
}

/** 会话主体列表；`include_deleted` 决定是否把「只剩已删除会话」的主体也算进去。 */
export async function listConversationPrincipals(
  platformId: number,
  query: ConversationPrincipalQuery = {}
): Promise<ConversationPrincipalPage> {
  const { data } = await http.get<BackendPage<ConversationPrincipal>>(
    `/platforms/${platformId}/conversation-principals`,
    {
      params: {
        page: query.page,
        page_size: query.pageSize,
        principal_type: query.principal_type,
        keyword: query.keyword,
        include_deleted: query.include_deleted,
      },
    }
  )
  return toPage<ConversationPrincipal>(data, query.pageSize ?? 20)
}

/**
 * 会话详情：会话头 + 主体 + Agent + 消息数 + 会话级用量。
 *
 * 已软删除的会话也能读到，后台需要有办法回看「删了什么」的计费与消息。
 */
export async function getConversation(
  platformId: number,
  conversationId: number
): Promise<ConsoleConversationDetail> {
  const { data } = await http.get<ConsoleConversationDetail>(
    `/platforms/${platformId}/conversations/${conversationId}`
  )
  return data
}

/** 软删除会话：消息与用量记录都保留，只是默认列表不再显示。 */
export async function deleteConversation(
  platformId: number,
  conversationId: number
): Promise<void> {
  await http.delete(`/platforms/${platformId}/conversations/${conversationId}`)
}

/**
 * 把后台接口包成 ai-sdk 需要的 `ConversationHistorySource`。
 *
 * SDK 只认这两个方法，不知道背后是 HTTP、也不参与鉴权；平台隔离与 token 都留在
 * 本仓库的 api 层（见 docs/adr/0003-conversation-history-read-boundary.md）。
 */
export function createConversationHistorySource(
  platformId: number
): ConversationHistorySource {
  return {
    async listConversations(params: ConversationListParams) {
      const { data } = await http.get<BackendPage<ConversationSummaryPayload>>(
        `/platforms/${platformId}/conversations`,
        { params }
      )
      return {
        items: data?.items ?? [],
        total: Number(data?.total ?? 0),
        page: Number(data?.page ?? params.page ?? 1),
        page_size: Number(data?.page_size ?? params.page_size ?? 20),
      }
    },
    async listMessages(conversationId) {
      const { data } = await http.get<ConversationMessagePayload[]>(
        `/platforms/${platformId}/conversations/${conversationId}/messages`
      )
      return Array.isArray(data) ? data : []
    },
  }
}
