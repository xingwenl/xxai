import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Copy,
  ExternalLink,
  FileCode2,
  RefreshCw,
  Search,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  deleteAiHtmlPage,
  getAiHtmlPages,
  type AiHtmlPage,
} from '@/api/ai-html-page'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { ThemeSwitch } from '@/components/theme-switch'
import { formatDateTime } from '@/lib/time'


const PAGE_SIZE = 10

type AiHtmlPagesPageProps = {
  search: {
    page?: number
    pageSize?: number
    title?: string
  }
  navigate: (opts: {
    search: (prev: Record<string, unknown>) => Record<string, unknown>
    replace?: boolean
  }) => void
}

export function AiHtmlPagesPage({
  search,
  navigate,
}: AiHtmlPagesPageProps) {
  const queryClient = useQueryClient()
  const [keyword, setKeyword] = useState(search.title ?? '')
  const [deletingPage, setDeletingPage] = useState<AiHtmlPage | null>(null)

  const page = search.page ?? 1
  const pageSize = search.pageSize ?? PAGE_SIZE

  const listQuery = useQuery({
    queryKey: ['system', 'ai-html-pages', { page, pageSize, title: search.title }],
    queryFn: () => getAiHtmlPages({ page, pageSize, title: search.title }),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteAiHtmlPage(id),
    onSuccess: async () => {
      toast.success('HTML 页面已删除')
      setDeletingPage(null)
      await queryClient.invalidateQueries({ queryKey: ['system', 'ai-html-pages'] })
    },
  })

  const pageData = listQuery.data
  const totalPage = Math.max(pageData?.totalPage ?? 1, 1)

  const updateSearch = (patch: Record<string, unknown>) => {
    navigate({
      search: (prev) => ({
        ...prev,
        ...patch,
      }),
    })
  }

  const submitSearch = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    updateSearch({ page: undefined, title: keyword.trim() || undefined })
  }

  const copyLink = async (publicPath: string) => {
    const absoluteUrl = toAbsoluteUrl(publicPath)
    try {
      await navigator.clipboard.writeText(absoluteUrl)
      toast.success('链接已复制')
    } catch {
      toast.error('复制失败，请手动复制链接')
    }
  }

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
        <div className='flex flex-wrap items-end justify-between gap-3'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>AI HTML 列表</h2>
            <p className='text-muted-foreground'>
              查看聊天 AI 创建的 HTML 页面，支持打开公开链接、复制链接与删除。
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <Button
              variant='outline'
              size='sm'
              onClick={() => listQuery.refetch()}
              disabled={listQuery.isFetching}
            >
              <RefreshCw className='me-2 size-4' />
              刷新
            </Button>
          </div>
        </div>

        <form
          className='flex w-full max-w-md items-center gap-2'
          onSubmit={submitSearch}
        >
          <div className='relative flex-1'>
            <Search className='absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground' />
            <Input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder='搜索页面标题'
              className='ps-9'
            />
          </div>
          <Button type='submit' variant='secondary'>
            搜索
          </Button>
        </form>

        <div className='overflow-hidden rounded-md border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>页面</TableHead>
                <TableHead>会话 ID</TableHead>
                <TableHead>公开链接</TableHead>
                <TableHead>更新时间</TableHead>
                <TableHead className='w-40 text-end'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {listQuery.isLoading ? (
                Array.from({ length: 5 }).map((_, index) => (
                  <TableRow key={index}>
                    <TableCell colSpan={5}>
                      <Skeleton className='h-8 w-full' />
                    </TableCell>
                  </TableRow>
                ))
              ) : pageData?.items.length ? (
                pageData.items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell>
                      <div className='flex items-center gap-3'>
                        <div className='flex size-9 items-center justify-center rounded-md bg-muted'>
                          <FileCode2 className='size-4 text-muted-foreground' />
                        </div>
                        <div>
                          <div className='font-medium'>{item.title}</div>
                          <div className='text-xs text-muted-foreground'>
                            slug: {item.slug}
                          </div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>{item.conversationId}</TableCell>
                    <TableCell className='max-w-xs truncate'>
                      <a
                        href={toAbsoluteUrl(item.publicPath)}
                        target='_blank'
                        rel='noreferrer'
                        className='text-primary underline-offset-4 hover:underline'
                      >
                        {item.publicPath}
                      </a>
                    </TableCell>
                    <TableCell>{formatDateTime(item.updatedAt)}</TableCell>
                    <TableCell className='text-end'>
                      <div className='flex justify-end gap-2'>
                        <Button
                          size='icon'
                          variant='ghost'
                          asChild
                        >
                          <a
                            href={toAbsoluteUrl(item.publicPath)}
                            target='_blank'
                            rel='noreferrer'
                          >
                            <ExternalLink className='size-4' />
                            <span className='sr-only'>打开链接</span>
                          </a>
                        </Button>
                        <Button
                          size='icon'
                          variant='ghost'
                          onClick={() => copyLink(item.publicPath)}
                        >
                          <Copy className='size-4' />
                          <span className='sr-only'>复制链接</span>
                        </Button>
                        <Button
                          size='icon'
                          variant='ghost'
                          className='text-destructive hover:text-destructive'
                          onClick={() => setDeletingPage(item)}
                        >
                          <Trash2 className='size-4' />
                          <span className='sr-only'>删除页面</span>
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={5} className='h-24 text-center'>
                    暂无 AI HTML 页面
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>

        <div className='flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground'>
          <div>
            共 {pageData?.total ?? 0} 条，第 {page} / {totalPage} 页
          </div>
          <div className='flex items-center gap-2'>
            <Button
              variant='outline'
              size='sm'
              disabled={page <= 1 || listQuery.isFetching}
              onClick={() => updateSearch({ page: page - 1 })}
            >
              上一页
            </Button>
            <Button
              variant='outline'
              size='sm'
              disabled={page >= totalPage || listQuery.isFetching}
              onClick={() => updateSearch({ page: page + 1 })}
            >
              下一页
            </Button>
          </div>
        </div>
      </Main>

      <AlertDialog
        open={!!deletingPage}
        onOpenChange={(open) => !open && setDeletingPage(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除 HTML 页面</AlertDialogTitle>
            <AlertDialogDescription>
              确认删除 {deletingPage?.title}？删除后原公开链接将无法继续访问。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deletingPage && deleteMutation.mutate(deletingPage.id)}
              className='text-destructive-foreground bg-destructive hover:bg-destructive/90'
            >
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function toAbsoluteUrl(publicPath: string) {
  if (/^https?:\/\//.test(publicPath)) {
    return publicPath
  }

  if (typeof window === 'undefined') {
    return publicPath
  }

  return new URL(publicPath, window.location.origin).toString()
}
