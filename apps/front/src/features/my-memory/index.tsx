import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Brain,
  History,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  clearMemories,
  createMemory,
  deleteMemory,
  listMemories,
  updateMemory,
  type MemoryItem,
  type MemoryKind,
} from '@/api/memory'
import { listPlatforms } from '@/api/platform'
import { formatDateTime } from '@/lib/time'
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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { ThemeSwitch } from '@/components/theme-switch'

/**
 * 用户记忆页：只展示「当前登录用户本人」的记忆，没有代查他人的入口。
 *
 * 这一页存在的意义不是「配置」，而是让自动写入可见、可改、可删——模型在
 * 聊天里记下的内容（以及记错的内容）必须能在这里被用户当场纠正。
 */

type MemoryForm = {
  kind: MemoryKind
  key: string
  content: string
  occurredAt: string
}

const EMPTY_FORM: MemoryForm = {
  kind: 'fact',
  key: '',
  content: '',
  occurredAt: '',
}

function toIso(value: string): string | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

function toLocalInput(value: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

export function MyMemoryPage() {
  const queryClient = useQueryClient()
  const [platformId, setPlatformId] = useState<number>()
  const [kindFilter, setKindFilter] = useState<'all' | MemoryKind>('all')
  const [includeHistory, setIncludeHistory] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<MemoryItem | 'create' | null>(null)
  const [form, setForm] = useState<MemoryForm>(EMPTY_FORM)
  const [deleting, setDeleting] = useState<MemoryItem | null>(null)
  const [clearing, setClearing] = useState(false)

  const platformsQuery = useQuery({
    queryKey: ['platforms'],
    queryFn: listPlatforms,
  })
  const activePlatformId = platformId ?? platformsQuery.data?.[0]?.id

  const memoriesQuery = useQuery({
    queryKey: [
      'memories',
      activePlatformId,
      kindFilter,
      includeHistory,
      search,
    ],
    queryFn: () =>
      listMemories(activePlatformId!, {
        kind: kindFilter === 'all' ? undefined : kindFilter,
        includeHistory,
        query: search || undefined,
      }),
    enabled: activePlatformId != null,
  })

  const data = memoriesQuery.data
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['memories', activePlatformId] })

  const saveMutation = useMutation({
    mutationFn: async (payload: MemoryForm) => {
      const occurredAt = toIso(payload.occurredAt)
      if (editing === 'create') {
        return createMemory(activePlatformId!, {
          kind: payload.kind,
          key: payload.kind === 'fact' ? payload.key.trim() : null,
          content: payload.content.trim(),
          occurred_at: occurredAt,
        })
      }
      return updateMemory(activePlatformId!, (editing as MemoryItem).id, {
        content: payload.content.trim(),
        occurred_at: occurredAt,
      })
    },
    onSuccess: () => {
      toast.success(editing === 'create' ? '记忆已保存' : '记忆已更新')
      setEditing(null)
      setForm(EMPTY_FORM)
      void invalidate()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteMemory(activePlatformId!, id),
    onSuccess: () => {
      toast.success('记忆已删除')
      setDeleting(null)
      void invalidate()
    },
  })

  const clearMutation = useMutation({
    mutationFn: () => clearMemories(activePlatformId!),
    onSuccess: (deleted) => {
      toast.success(`已清空 ${deleted} 条记忆`)
      setClearing(false)
      void invalidate()
    },
  })

  const counts = useMemo(
    () => ({
      fact: data?.fact_count ?? 0,
      event: data?.event_count ?? 0,
    }),
    [data?.event_count, data?.fact_count]
  )

  const openCreate = () => {
    setForm(EMPTY_FORM)
    setEditing('create')
  }

  const openEdit = (item: MemoryItem) => {
    setForm({
      kind: item.kind,
      key: item.key ?? '',
      content: item.content,
      occurredAt: toLocalInput(item.occurred_at),
    })
    setEditing(item)
  }

  const submit = () => {
    if (!form.content.trim()) {
      toast.error('请填写记忆内容')
      return
    }
    if (editing === 'create' && form.kind === 'fact' && !form.key.trim()) {
      toast.error('事实需要填写标识（如「城市」「姓名」）')
      return
    }
    saveMutation.mutate(form)
  }

  const isCreating = editing === 'create'

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
            <div className='mb-2 flex items-center gap-2 text-xs font-medium tracking-[0.14em] text-muted-foreground uppercase'>
              <Brain className='size-4' />
              我的空间 / 用户记忆
            </div>
            <h1 className='text-2xl font-bold tracking-tight'>用户记忆</h1>
            <p className='mt-1 max-w-2xl text-sm text-muted-foreground'>
              智能体在聊天里记住的、以及你自己添加的个人信息。记忆内容不会预先注入
              对话，只有被问到时才会按需检索；这里可以修改或删除任何一条。
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <Button variant='outline' size='sm' onClick={openCreate}>
              <Plus className='size-4' />
              新增记忆
            </Button>
            <Button
              variant='outline'
              size='sm'
              onClick={() => void memoriesQuery.refetch()}
              disabled={memoriesQuery.isFetching}
            >
              <RefreshCw className='size-4' />
              刷新
            </Button>
            <Button
              variant='outline'
              size='sm'
              className='text-destructive'
              onClick={() => setClearing(true)}
              disabled={!data || data.total === 0}
            >
              <Trash2 className='size-4' />
              清空
            </Button>
          </div>
        </div>

        <div className='flex flex-wrap items-center gap-2'>
          <Badge variant='secondary'>事实 {counts.fact}</Badge>
          <Badge variant='secondary'>经历 {counts.event}</Badge>
          <div className='ms-auto flex flex-wrap items-center gap-2'>
            <div className='flex items-center gap-2'>
              <Label className='text-muted-foreground text-xs'>平台</Label>
              <Select
                value={activePlatformId ? String(activePlatformId) : ''}
                onValueChange={(value) => setPlatformId(Number(value))}
              >
                <SelectTrigger className='w-44'>
                  <SelectValue placeholder='选择平台' />
                </SelectTrigger>
                <SelectContent>
                  {platformsQuery.data?.map((platform) => (
                    <SelectItem key={platform.id} value={String(platform.id)}>
                      {platform.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Select
              value={kindFilter}
              onValueChange={(value) =>
                setKindFilter(value as 'all' | MemoryKind)
              }
            >
              <SelectTrigger className='w-32'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value='all'>全部</SelectItem>
                <SelectItem value='fact'>事实</SelectItem>
                <SelectItem value='event'>经历</SelectItem>
              </SelectContent>
            </Select>
            <Button
              variant={includeHistory ? 'default' : 'outline'}
              size='sm'
              onClick={() => setIncludeHistory((value) => !value)}
            >
              <History className='size-4' />
              含历史
            </Button>
            <div className='relative'>
              <Search className='text-muted-foreground absolute top-2.5 left-2.5 size-4' />
              <Input
                className='w-56 pl-8'
                placeholder='搜索内容或标识'
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') setSearch(keyword.trim())
                }}
              />
            </div>
            <Button
              variant='outline'
              size='sm'
              onClick={() => setSearch(keyword.trim())}
            >
              搜索
            </Button>
          </div>
        </div>

        <div className='rounded-lg border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className='w-20'>类别</TableHead>
                <TableHead className='w-28'>标识</TableHead>
                <TableHead>内容</TableHead>
                <TableHead className='w-40'>时间</TableHead>
                <TableHead className='w-20'>来源</TableHead>
                <TableHead className='w-28 text-right'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {memoriesQuery.isLoading ? (
                Array.from({ length: 4 }).map((_, index) => (
                  <TableRow key={index}>
                    <TableCell colSpan={6}>
                      <Skeleton className='h-6 w-full' />
                    </TableCell>
                  </TableRow>
                ))
              ) : data && data.items.length > 0 ? (
                data.items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell>
                      <Badge
                        variant={item.kind === 'fact' ? 'default' : 'secondary'}
                      >
                        {item.kind === 'fact' ? '事实' : '经历'}
                      </Badge>
                    </TableCell>
                    <TableCell className='text-muted-foreground text-sm'>
                      {item.key ?? '—'}
                    </TableCell>
                    <TableCell>
                      <div className='flex flex-col gap-1'>
                        <span className='text-sm'>{item.content}</span>
                        {!item.is_active && (
                          <span className='text-muted-foreground text-xs'>
                            已于 {formatDateTime(item.valid_until ?? '')} 被新值覆盖
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className='text-muted-foreground text-sm'>
                      {item.occurred_at ? formatDateTime(item.occurred_at) : '—'}
                    </TableCell>
                    <TableCell>
                      <Badge variant='outline'>
                        {item.source === 'explicit' ? '手动' : '自动'}
                      </Badge>
                    </TableCell>
                    <TableCell className='text-right'>
                      <Button
                        variant='ghost'
                        size='icon'
                        onClick={() => openEdit(item)}
                      >
                        <Pencil className='size-4' />
                      </Button>
                      <Button
                        variant='ghost'
                        size='icon'
                        className='text-destructive'
                        onClick={() => setDeleting(item)}
                      >
                        <Trash2 className='size-4' />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell
                    colSpan={6}
                    className='text-muted-foreground py-10 text-center text-sm'
                  >
                    还没有记忆。在聊天里说「记住……」即可让智能体记下，也可以点
                    「新增记忆」手动添加。
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </Main>

      <Dialog
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) setEditing(null)
        }}
      >
        <DialogContent className='sm:max-w-lg'>
          <DialogHeader>
            <DialogTitle>{isCreating ? '新增记忆' : '编辑记忆'}</DialogTitle>
            <DialogDescription>
              事实按标识覆盖（旧值保留时间线）；经历只追加，适合记录「做过什么」。
            </DialogDescription>
          </DialogHeader>
          <div className='flex flex-col gap-4'>
            {isCreating && (
              <div className='flex flex-col gap-2'>
                <Label>类别</Label>
                <Select
                  value={form.kind}
                  onValueChange={(value) =>
                    setForm((prev) => ({
                      ...prev,
                      kind: value as MemoryKind,
                    }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='fact'>事实（稳定信息，可覆盖）</SelectItem>
                    <SelectItem value='event'>经历（一次性事件，只追加）</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
            {isCreating && form.kind === 'fact' && (
              <div className='flex flex-col gap-2'>
                <Label>标识</Label>
                <Input
                  placeholder='如：城市、姓名、时区、长期项目'
                  value={form.key}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, key: event.target.value }))
                  }
                />
              </div>
            )}
            <div className='flex flex-col gap-2'>
              <Label>内容</Label>
              <Textarea
                rows={4}
                placeholder='写成一句脱离上下文也能读懂的话'
                value={form.content}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, content: event.target.value }))
                }
              />
            </div>
            <div className='flex flex-col gap-2'>
              <Label>
                {isCreating && form.kind === 'event' ? '发生时间' : '生效时间'}
              </Label>
              <Input
                type='datetime-local'
                value={form.occurredAt}
                onChange={(event) =>
                  setForm((prev) => ({
                    ...prev,
                    occurredAt: event.target.value,
                  }))
                }
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant='outline' onClick={() => setEditing(null)}>
              取消
            </Button>
            <Button onClick={submit} disabled={saveMutation.isPending}>
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除这条记忆？</AlertDialogTitle>
            <AlertDialogDescription>
              「{deleting?.content}」删除后不可恢复，智能体也不会再记起它。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleting && deleteMutation.mutate(deleting.id)}
            >
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={clearing} onOpenChange={setClearing}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>清空全部记忆？</AlertDialogTitle>
            <AlertDialogDescription>
              将删除当前账号在本平台保存的全部记忆（含历史值），操作不可恢复。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={() => clearMutation.mutate()}>
              清空
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
