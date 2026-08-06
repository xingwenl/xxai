import { useRef, useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Database,
  Edit,
  ExternalLink,
  Link2,
  Plus,
  RefreshCw,
  RotateCw,
  Server,
  Trash2,
  Upload,
} from 'lucide-react'
import { toast } from 'sonner'
import { listAgents, type Agent } from '@/api/agent'
import {
  bindKnowledgeBaseAgent,
  createKnowledgeBase,
  createUrlDocument,
  deleteKnowledgeBase,
  deleteKnowledgeDocument,
  listKnowledgeBases,
  listKnowledgeDocuments,
  retryKnowledgeDocument,
  updateKnowledgeBase,
  uploadKnowledgeDocument,
  type KnowledgeBase,
  type KnowledgeBaseInput,
  type KnowledgeDocument,
} from '@/api/knowledge'
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
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { ThemeSwitch } from '@/components/theme-switch'

const baseSchema = z.object({
  name: z.string().min(1, '请输入名称').max(120),
  slug: z
    .string()
    .min(2, '至少 2 个字符')
    .regex(/^[a-z0-9][a-z0-9_-]*$/, '只允许小写字母、数字、下划线和短横线'),
  embedding_model: z.string().min(1, '请输入 embedding 模型'),
  embedding_base_url: z
    .string()
    .url('请输入有效 URL')
    .optional()
    .or(z.literal('')),
  embedding_api_key: z.string().optional(),
  embedding_dimension: z.coerce.number().int().min(1).max(65535),
  chunk_size: z.coerce.number().int().min(32).max(8192),
  chunk_overlap: z.coerce.number().int().min(0).max(2048),
  retrieval_threshold: z.coerce.number().min(0).max(1),
  retrieval_top_k: z.coerce.number().int().min(1).max(20),
})
const urlSchema = z.object({
  url: z.string().url('请输入有效 URL'),
  title: z.string().max(255).optional(),
})
type BaseFormInput = z.input<typeof baseSchema>
type BaseForm = z.output<typeof baseSchema>
type UrlForm = z.infer<typeof urlSchema>

export function KnowledgeBasesPage() {
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const [platformId, setPlatformId] = useState<number>()
  const [selectedBase, setSelectedBase] = useState<KnowledgeBase | null>(null)
  const [editing, setEditing] = useState<KnowledgeBase | null | undefined>()
  const [binding, setBinding] = useState<KnowledgeBase | null>(null)
  const [deleting, setDeleting] = useState<KnowledgeBase | null>(null)
  const [deletingDocument, setDeletingDocument] =
    useState<KnowledgeDocument | null>(null)
  const [urlOpen, setUrlOpen] = useState(false)
  const platformsQuery = useQuery({
    queryKey: ['platforms'],
    queryFn: listPlatforms,
  })
  const activePlatformId = platformId ?? platformsQuery.data?.[0]?.id
  const basesQuery = useQuery({
    queryKey: ['knowledge-bases', activePlatformId],
    queryFn: () => listKnowledgeBases(activePlatformId!),
    enabled: activePlatformId != null,
  })
  const activeBase =
    selectedBase &&
    basesQuery.data?.items.some((item) => item.id === selectedBase.id)
      ? selectedBase
      : basesQuery.data?.items[0]
  const documentsQuery = useQuery({
    queryKey: ['knowledge-documents', activePlatformId, activeBase?.id],
    queryFn: () => listKnowledgeDocuments(activePlatformId!, activeBase!.id),
    enabled: activePlatformId != null && activeBase != null,
  })
  const invalidateBases = () =>
    queryClient.invalidateQueries({
      queryKey: ['knowledge-bases', activePlatformId],
    })
  const invalidateDocuments = () =>
    queryClient.invalidateQueries({
      queryKey: ['knowledge-documents', activePlatformId, activeBase?.id],
    })
  const saveMutation = useMutation({
    mutationFn: (values: BaseForm) => {
      if (!activePlatformId) throw new Error('请选择平台')
      const input: KnowledgeBaseInput = {
        ...values,
        embedding_dimension: Number(values.embedding_dimension),
        chunk_size: Number(values.chunk_size),
        chunk_overlap: Number(values.chunk_overlap),
        retrieval_threshold: Number(values.retrieval_threshold),
        retrieval_top_k: Number(values.retrieval_top_k),
      }
      return editing
        ? updateKnowledgeBase(activePlatformId, editing.id, input)
        : createKnowledgeBase(activePlatformId, input)
    },
    onSuccess: async (base) => {
      toast.success(editing ? '知识库已更新' : '知识库已创建')
      setEditing(undefined)
      setSelectedBase(base)
      await invalidateBases()
    },
  })
  const deleteMutation = useMutation({
    mutationFn: (base: KnowledgeBase) =>
      deleteKnowledgeBase(activePlatformId!, base.id),
    onSuccess: async () => {
      toast.success('知识库及文档已删除')
      setDeleting(null)
      setSelectedBase(null)
      await invalidateBases()
    },
  })
  const uploadMutation = useMutation({
    mutationFn: (file: File) =>
      uploadKnowledgeDocument(activePlatformId!, activeBase!.id, file),
    onSuccess: async () => {
      toast.success('文档已加入处理队列')
      await invalidateDocuments()
    },
  })
  const urlMutation = useMutation({
    mutationFn: (values: UrlForm) =>
      createUrlDocument(activePlatformId!, activeBase!.id, values),
    onSuccess: async () => {
      toast.success('URL 文档已加入处理队列')
      setUrlOpen(false)
      await invalidateDocuments()
    },
  })
  const documentDeleteMutation = useMutation({
    mutationFn: (document: KnowledgeDocument) =>
      deleteKnowledgeDocument(activePlatformId!, activeBase!.id, document.id),
    onSuccess: async () => {
      toast.success('文档已删除')
      setDeletingDocument(null)
      await invalidateDocuments()
    },
  })
  const retryMutation = useMutation({
    mutationFn: (document: KnowledgeDocument) =>
      retryKnowledgeDocument(activePlatformId!, activeBase!.id, document.id),
    onSuccess: async () => {
      toast.success('文档已重新排队')
      await invalidateDocuments()
    },
  })
  const bindAgentMutation = useMutation({
    mutationFn: ({ base, agentId }: { base: KnowledgeBase; agentId: number }) =>
      bindKnowledgeBaseAgent(activePlatformId!, base.id, agentId),
    onSuccess: async () => {
      toast.success('知识库已绑定到智能体')
      setBinding(null)
      await invalidateBases()
    },
  })
  const selectedPlatform = platformsQuery.data?.find(
    (item) => item.id === activePlatformId
  )
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
            <h2 className='text-2xl font-bold tracking-tight'>知识库管理</h2>
            <p className='text-muted-foreground'>
              配置检索知识源，并跟踪文档入库状态。
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <Select
              value={activePlatformId?.toString()}
              onValueChange={(value) => {
                setPlatformId(Number(value))
                setSelectedBase(null)
              }}
            >
              <SelectTrigger className='w-52'>
                <SelectValue placeholder='选择平台' />
              </SelectTrigger>
              <SelectContent>
                {(platformsQuery.data ?? []).map((platform) => (
                  <SelectItem key={platform.id} value={platform.id.toString()}>
                    {platform.name} ({platform.code})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant='outline'
              size='sm'
              onClick={() => basesQuery.refetch()}
              disabled={!activePlatformId || basesQuery.isFetching}
            >
              <RefreshCw className='size-4' />
              刷新
            </Button>
            <Button
              size='sm'
              onClick={() => setEditing(null)}
              disabled={!activePlatformId}
            >
              <Plus className='size-4' />
              新建知识库
            </Button>
          </div>
        </div>
        <div className='rounded-md border bg-muted/30 px-4 py-3 text-sm'>
          <Server className='me-2 inline size-4' />
          当前平台：{selectedPlatform?.name ?? '未选择平台'}
        </div>
        <div className='grid min-h-0 gap-4 xl:grid-cols-[minmax(360px,0.9fr)_minmax(0,1.5fr)]'>
          <section className='overflow-hidden rounded-md border'>
            <div className='border-b px-4 py-3'>
              <div className='flex items-center justify-between'>
                <h3 className='font-semibold'>知识库</h3>
                <Badge variant='outline'>{basesQuery.data?.total ?? 0}</Badge>
              </div>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>名称</TableHead>
                  <TableHead>模型</TableHead>
                  <TableHead className='w-24 text-end'>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {basesQuery.isLoading
                  ? Array.from({ length: 4 }).map((_, i) => (
                      <TableRow key={i}>
                        <TableCell colSpan={3}>
                          <Skeleton className='h-8 w-full' />
                        </TableCell>
                      </TableRow>
                    ))
                  : (basesQuery.data?.items ?? []).map((base) => (
                      <TableRow
                        key={base.id}
                        data-state={
                          activeBase?.id === base.id ? 'selected' : undefined
                        }
                        className='cursor-pointer'
                        onClick={() => setSelectedBase(base)}
                      >
                        <TableCell>
                          <div className='flex items-center gap-3'>
                            <div className='flex size-9 items-center justify-center rounded-md bg-muted'>
                              <Database className='size-4 text-muted-foreground' />
                            </div>
                            <div>
                              <div className='font-medium'>{base.name}</div>
                              <div className='text-xs text-muted-foreground'>
                                {base.slug} · v{base.active_index_version}
                              </div>
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className='max-w-32 truncate text-xs'>
                          {base.embedding_model}
                        </TableCell>
                        <TableCell>
                          <div className='flex justify-end gap-1'>
                            <Button
                              size='icon'
                              variant='ghost'
                              onClick={(event) => {
                                event.stopPropagation()
                                setEditing(base)
                              }}
                            >
                              <Edit className='size-4' />
                              <span className='sr-only'>编辑</span>
                            </Button>
                            <Button
                              size='icon'
                              variant='ghost'
                              onClick={(event) => {
                                event.stopPropagation()
                                setBinding(base)
                              }}
                            >
                              <Link2 className='size-4' />
                              <span className='sr-only'>绑定智能体</span>
                            </Button>
                            <Button
                              size='icon'
                              variant='ghost'
                              className='text-destructive hover:text-destructive'
                              onClick={(event) => {
                                event.stopPropagation()
                                setDeleting(base)
                              }}
                            >
                              <Trash2 className='size-4' />
                              <span className='sr-only'>删除</span>
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                {!basesQuery.isLoading && !basesQuery.data?.items.length && (
                  <TableRow>
                    <TableCell
                      colSpan={3}
                      className='h-24 text-center text-muted-foreground'
                    >
                      暂无知识库
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </section>
          <section className='overflow-hidden rounded-md border'>
            <div className='flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3'>
              <div>
                <h3 className='font-semibold'>
                  {activeBase?.name ?? '文档管理'}
                </h3>
                <p className='text-xs text-muted-foreground'>
                  {activeBase
                    ? `${activeBase.embedding_dimension} 维 · 分块 ${activeBase.chunk_size}/${activeBase.chunk_overlap} · 阈值 ${activeBase.retrieval_threshold} · Top K ${activeBase.retrieval_top_k}`
                    : '请选择知识库'}
                </p>
              </div>
              <div className='flex gap-2'>
                <Button
                  size='sm'
                  variant='outline'
                  onClick={() => fileInput.current?.click()}
                  disabled={!activeBase || uploadMutation.isPending}
                >
                  <Upload className='size-4' />
                  上传文件
                </Button>
                <input
                  ref={fileInput}
                  type='file'
                  className='hidden'
                  accept='.txt,.md,.pdf,.docx'
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) uploadMutation.mutate(file)
                    event.target.value = ''
                  }}
                />
                <Button
                  size='sm'
                  onClick={() => setUrlOpen(true)}
                  disabled={!activeBase}
                >
                  <ExternalLink className='size-4' />
                  添加 URL
                </Button>
              </div>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>文档</TableHead>
                  <TableHead>来源</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>更新时间</TableHead>
                  <TableHead className='w-28 text-end'>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documentsQuery.isLoading
                  ? Array.from({ length: 4 }).map((_, i) => (
                      <TableRow key={i}>
                        <TableCell colSpan={5}>
                          <Skeleton className='h-8 w-full' />
                        </TableCell>
                      </TableRow>
                    ))
                  : (documentsQuery.data ?? []).map((document) => (
                      <TableRow key={document.id}>
                        <TableCell className='max-w-48'>
                          <div className='truncate font-medium'>
                            {document.title}
                          </div>
                          {document.error_message && (
                            <div className='truncate text-xs text-destructive'>
                              {document.error_message}
                            </div>
                          )}
                        </TableCell>
                        <TableCell className='text-xs'>
                          {document.source_type === 'file' ? '文件' : 'URL'}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={
                              document.status === 'ready'
                                ? 'default'
                                : document.status === 'failed'
                                  ? 'destructive'
                                  : 'secondary'
                            }
                          >
                            {document.status}
                          </Badge>
                        </TableCell>
                        <TableCell className='text-xs text-muted-foreground'>
                          {formatDateTime(document.updated_at)}
                        </TableCell>
                        <TableCell>
                          <div className='flex justify-end gap-1'>
                            {document.status === 'failed' && (
                              <Button
                                size='icon'
                                variant='ghost'
                                onClick={() => retryMutation.mutate(document)}
                                disabled={retryMutation.isPending}
                              >
                                <RotateCw className='size-4' />
                                <span className='sr-only'>重试</span>
                              </Button>
                            )}
                            <Button
                              size='icon'
                              variant='ghost'
                              className='text-destructive hover:text-destructive'
                              onClick={() => setDeletingDocument(document)}
                            >
                              <Trash2 className='size-4' />
                              <span className='sr-only'>删除</span>
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                {!documentsQuery.isLoading && !documentsQuery.data?.length && (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className='h-24 text-center text-muted-foreground'
                    >
                      {activeBase ? '暂无文档' : '请选择知识库'}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </section>
        </div>
      </Main>
      <KnowledgeBaseDialog
        base={editing && editing.id ? editing : null}
        open={editing !== undefined}
        onOpenChange={(open) => !open && setEditing(undefined)}
        isSaving={saveMutation.isPending}
        onSubmit={(values) => saveMutation.mutate(values)}
      />
      <UrlDocumentDialog
        open={urlOpen}
        onOpenChange={setUrlOpen}
        isSaving={urlMutation.isPending}
        onSubmit={(values) => urlMutation.mutate(values)}
      />
      {activePlatformId && (
        <KnowledgeAgentBindingDialog
          platformId={activePlatformId}
          base={binding}
          open={!!binding}
          onOpenChange={(open) => !open && setBinding(null)}
          isSaving={bindAgentMutation.isPending}
          onSubmit={(agentId) =>
            binding && bindAgentMutation.mutate({ base: binding, agentId })
          }
        />
      )}
      <AlertDialog
        open={!!deleting}
        onOpenChange={(open) => !open && setDeleting(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>硬删除知识库</AlertDialogTitle>
            <AlertDialogDescription>
              确认删除 {deleting?.name}
              ？所有文档、向量切片和入库任务将永久删除。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              className='text-destructive-foreground bg-destructive hover:bg-destructive/90'
              onClick={() => deleting && deleteMutation.mutate(deleting)}
            >
              永久删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog
        open={!!deletingDocument}
        onOpenChange={(open) => !open && setDeletingDocument(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除文档</AlertDialogTitle>
            <AlertDialogDescription>
              确认删除 {deletingDocument?.title}？该文档及其向量切片将永久删除。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              className='text-destructive-foreground bg-destructive hover:bg-destructive/90'
              onClick={() =>
                deletingDocument &&
                documentDeleteMutation.mutate(deletingDocument)
              }
            >
              永久删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function KnowledgeBaseDialog({
  base,
  open,
  onOpenChange,
  isSaving,
  onSubmit,
}: {
  base: KnowledgeBase | null
  open: boolean
  onOpenChange: (open: boolean) => void
  isSaving: boolean
  onSubmit: (values: BaseForm) => void
}) {
  const form = useForm<BaseFormInput, unknown, BaseForm>({
    resolver: zodResolver(baseSchema),
    values: {
      name: base?.name ?? '',
      slug: base?.slug ?? '',
      embedding_model: base?.embedding_model ?? 'text-embedding-3-small',
      embedding_base_url: base?.embedding_base_url ?? '',
      embedding_api_key: '',
      embedding_dimension: base?.embedding_dimension ?? 1536,
      chunk_size: base?.chunk_size ?? 512,
      chunk_overlap: base?.chunk_overlap ?? 50,
      retrieval_threshold: base?.retrieval_threshold ?? 0.5,
      retrieval_top_k: base?.retrieval_top_k ?? 5,
    },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-w-2xl'>
        <DialogHeader>
          <DialogTitle>{base ? '编辑知识库' : '新建知识库'}</DialogTitle>
          <DialogDescription>
            API Key 只写入加密存储，保存后不会回显。
          </DialogDescription>
        </DialogHeader>
        <form
          id='knowledge-base-form'
          onSubmit={form.handleSubmit(onSubmit)}
          className='grid gap-4 sm:grid-cols-2'
        >
          {(
            [
              'name',
              'slug',
              'embedding_model',
              'embedding_base_url',
              'embedding_api_key',
              'embedding_dimension',
              'chunk_size',
              'chunk_overlap',
              'retrieval_threshold',
              'retrieval_top_k',
            ] as const
          ).map((name) => (
            <div
              key={name}
              className={
                name === 'embedding_api_key' || name === 'embedding_base_url'
                  ? 'sm:col-span-2'
                  : ''
              }
            >
              <Label htmlFor={name}>
                {
                  {
                    name: '名称',
                    slug: 'Slug',
                    embedding_model: 'Embedding 模型',
                    embedding_base_url: 'Embedding Base URL',
                    embedding_api_key: 'Embedding API Key',
                    embedding_dimension: '向量维度',
                    chunk_size: '分块大小',
                    chunk_overlap: '分块重叠',
                    retrieval_threshold: '相似度阈值',
                    retrieval_top_k: '检索 Top K',
                  }[name]
                }
              </Label>
              <Input
                id={name}
                type={
                  name.includes('dimension') ||
                  name.includes('size') ||
                  name.includes('overlap') ||
                  name.includes('threshold') ||
                  name.includes('top_k')
                    ? 'number'
                    : name.includes('key')
                      ? 'password'
                      : 'text'
                }
                step={name === 'retrieval_threshold' ? '0.01' : undefined}
                disabled={base != null && name === 'slug'}
                {...form.register(name)}
              />
              <p className='mt-1 text-xs text-destructive'>
                {form.formState.errors[name]?.message}
              </p>
            </div>
          ))}
        </form>
        <DialogFooter>
          <Button type='submit' form='knowledge-base-form' disabled={isSaving}>
            {isSaving ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function UrlDocumentDialog({
  open,
  onOpenChange,
  isSaving,
  onSubmit,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  isSaving: boolean
  onSubmit: (values: UrlForm) => void
}) {
  const form = useForm<UrlForm>({
    resolver: zodResolver(urlSchema),
    defaultValues: { url: '', title: '' },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>添加 URL 文档</DialogTitle>
          <DialogDescription>
            服务端会异步抓取公开 HTTP/HTTPS 页面并建立索引。
          </DialogDescription>
        </DialogHeader>
        <form
          id='url-document-form'
          onSubmit={form.handleSubmit(onSubmit)}
          className='grid gap-4'
        >
          <div>
            <Label htmlFor='document-url'>URL</Label>
            <Input
              id='document-url'
              placeholder='https://example.com/docs'
              {...form.register('url')}
            />
            <p className='mt-1 text-xs text-destructive'>
              {form.formState.errors.url?.message}
            </p>
          </div>
          <div>
            <Label htmlFor='document-title'>标题（可选）</Label>
            <Input id='document-title' {...form.register('title')} />
          </div>
        </form>
        <DialogFooter>
          <Button type='submit' form='url-document-form' disabled={isSaving}>
            {isSaving ? '提交中...' : '加入处理队列'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function KnowledgeAgentBindingDialog({
  platformId,
  base,
  open,
  onOpenChange,
  isSaving,
  onSubmit,
}: {
  platformId: number
  base: KnowledgeBase | null
  open: boolean
  onOpenChange: (open: boolean) => void
  isSaving: boolean
  onSubmit: (agentId: number) => void
}) {
  const [agentId, setAgentId] = useState<number>()
  const agentsQuery = useQuery({
    queryKey: ['agents', platformId],
    queryFn: () => listAgents(platformId),
    enabled: open,
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{base?.name ?? '知识库'} · 绑定智能体</DialogTitle>
          <DialogDescription>
            绑定后，该智能体聊天时会检索并注入此知识库的匹配片段。
          </DialogDescription>
        </DialogHeader>
        <div className='grid gap-3'>
          <Label htmlFor='knowledge-agent'>智能体</Label>
          <Select
            value={agentId?.toString()}
            onValueChange={(value) => setAgentId(Number(value))}
            disabled={agentsQuery.isLoading}
          >
            <SelectTrigger id='knowledge-agent'>
              <SelectValue
                placeholder={
                  agentsQuery.isLoading ? '读取智能体中...' : '选择智能体'
                }
              />
            </SelectTrigger>
            <SelectContent>
              {(agentsQuery.data?.items ?? []).map((agent: Agent) => (
                <SelectItem key={agent.id} value={agent.id.toString()}>
                  {agent.name} ({agent.slug})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {!agentsQuery.isLoading && !agentsQuery.data?.items.length && (
            <p className='text-sm text-muted-foreground'>
              当前平台暂无可绑定的智能体。
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant='outline' onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button
            onClick={() => agentId && onSubmit(agentId)}
            disabled={!agentId || isSaving}
          >
            {isSaving ? '绑定中...' : '绑定'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
