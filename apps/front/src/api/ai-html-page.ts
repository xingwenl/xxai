import { http } from '@/lib/http'
import type { Paginated } from './user'

export type AiHtmlPage = {
  id: number
  conversationId: number
  title: string
  slug: string
  publicPath: string
  createdAt?: string | null
  updatedAt?: string | null
}

export type ListAiHtmlPagesParams = {
  page?: number
  pageSize?: number
  title?: string
}

export async function getAiHtmlPages(
  params: ListAiHtmlPagesParams = {}
): Promise<Paginated<AiHtmlPage>> {
  const { data } = await http.get<Paginated<AiHtmlPage>>('/api/chat/html-pages', {
    params,
  })
  return normalizePage(data)
}

export async function deleteAiHtmlPage(
  id: number
): Promise<{ id: number; deleted: boolean }> {
  const { data } = await http.delete<{ id: number; deleted: boolean }>(
    `/api/chat/html-pages/${id}`
  )
  return data
}

function normalizePage<T>(page?: Paginated<T> | null): Paginated<T> {
  return {
    items: page?.items ?? [],
    total: Number(page?.total ?? 0),
    page: Number(page?.page ?? 1),
    pageSize: Number(page?.pageSize ?? 20),
    totalPage: Number(page?.totalPage ?? 0),
  }
}
