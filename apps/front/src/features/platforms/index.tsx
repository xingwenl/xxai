import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Edit, Plus, RefreshCw, Server, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import {
  createPlatform,
  deletePlatform,
  listPlatforms,
  updatePlatform,
  type Platform,
  type PlatformInput,
} from '@/api/platform'
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
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
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

type PlatformForm = PlatformInput & {
  is_active: boolean
}

const emptyForm: PlatformForm = {
  name: '',
  code: '',
  is_active: true,
}

export function PlatformsPage() {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<Platform | null | undefined>()
  const [deleting, setDeleting] = useState<Platform | null>(null)
  const platformsQuery = useQuery({
    queryKey: ['platforms'],
    queryFn: listPlatforms,
  })
  const invalidatePlatforms = () =>
    queryClient.invalidateQueries({ queryKey: ['platforms'] })
  const saveMutation = useMutation({
    mutationFn: (form: PlatformForm) => {
      const input: PlatformInput = {
        name: form.name.trim(),
        code: form.code.trim(),
      }
      return editing
        ? updatePlatform(editing.id, { ...input, is_active: form.is_active })
        : createPlatform(input)
    },
    onSuccess: async () => {
      toast.success(editing ? '平台已更新' : '平台已创建')
      setEditing(undefined)
      await invalidatePlatforms()
    },
  })
  const toggleMutation = useMutation({
    mutationFn: ({
      platform,
      is_active,
    }: {
      platform: Platform
      is_active: boolean
    }) =>
      updatePlatform(platform.id, {
        name: platform.name,
        code: platform.code,
        is_active,
      }),
    onSuccess: async () => {
      toast.success('平台状态已更新')
      await invalidatePlatforms()
    },
  })
  const deleteMutation = useMutation({
    mutationFn: (platform: Platform) => deletePlatform(platform.id),
    onSuccess: async () => {
      toast.success('平台已硬删除')
      setDeleting(null)
      await invalidatePlatforms()
    },
  })
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
            <h2 className='text-2xl font-bold tracking-tight'>平台管理</h2>
            <p className='text-muted-foreground'>
              管理平台基础信息、启用状态和平台级资源边界。
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <Button
              variant='outline'
              size='sm'
              onClick={() => platformsQuery.refetch()}
              disabled={platformsQuery.isFetching}
            >
              <RefreshCw className='size-4' />
              刷新
            </Button>
            <Button size='sm' onClick={() => setEditing(null)}>
              <Plus className='size-4' />
              新建平台
            </Button>
          </div>
        </div>
        <div className='overflow-hidden rounded-md border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>平台</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>创建时间</TableHead>
                <TableHead className='w-36 text-end'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {platformsQuery.isLoading
                ? Array.from({ length: 4 }).map((_, index) => (
                    <TableRow key={index}>
                      <TableCell colSpan={4}>
                        <Skeleton className='h-8 w-full' />
                      </TableCell>
                    </TableRow>
                  ))
                : (platformsQuery.data ?? []).map((platform) => (
                    <TableRow key={platform.id}>
                      <TableCell>
                        <div className='flex items-center gap-3'>
                          <div className='flex size-9 items-center justify-center rounded-md bg-muted'>
                            <Server className='size-4 text-muted-foreground' />
                          </div>
                          <div>
                            <div className='font-medium'>{platform.name}</div>
                            <div className='text-xs text-muted-foreground'>
                              {platform.code} · ID {platform.id}
                            </div>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className='flex items-center gap-2'>
                          <Switch
                            checked={platform.is_active}
                            disabled={toggleMutation.isPending}
                            onCheckedChange={(is_active) =>
                              toggleMutation.mutate({ platform, is_active })
                            }
                          />
                          <Badge
                            variant={
                              platform.is_active ? 'default' : 'secondary'
                            }
                          >
                            {platform.is_active ? '启用' : '停用'}
                          </Badge>
                        </div>
                      </TableCell>
                      <TableCell className='text-sm text-muted-foreground'>
                        {formatDateTime(platform.created_at)}
                      </TableCell>
                      <TableCell>
                        <div className='flex justify-end gap-1'>
                          <Button
                            size='icon'
                            variant='ghost'
                            onClick={() => setEditing(platform)}
                          >
                            <Edit className='size-4' />
                            <span className='sr-only'>编辑</span>
                          </Button>
                          <Button
                            size='icon'
                            variant='ghost'
                            className='text-destructive hover:text-destructive'
                            onClick={() => setDeleting(platform)}
                          >
                            <Trash2 className='size-4' />
                            <span className='sr-only'>硬删除</span>
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
              {!platformsQuery.isLoading && !platformsQuery.data?.length && (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className='h-24 text-center text-muted-foreground'
                  >
                    暂无平台
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
        <div className='text-sm text-muted-foreground'>
          共 {platformsQuery.data?.length ?? 0} 个平台
        </div>
      </Main>
      <PlatformDialog
        key={editing ? editing.id : 'new'}
        platform={editing && editing.id ? editing : null}
        open={editing !== undefined}
        onOpenChange={(open) => !open && setEditing(undefined)}
        isSaving={saveMutation.isPending}
        onSubmit={(form) => saveMutation.mutate(form)}
      />
      <AlertDialog
        open={!!deleting}
        onOpenChange={(open) => !open && setDeleting(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>硬删除平台</AlertDialogTitle>
            <AlertDialogDescription>
              确认硬删除 {deleting?.name}？平台下的
              Agent、知识库、Skill、MCP、Embed
              Client、宿主工具策略和会话相关数据可能被级联删除或受数据库约束影响。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              className='text-destructive-foreground bg-destructive hover:bg-destructive/90'
              onClick={() => deleting && deleteMutation.mutate(deleting)}
            >
              硬删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function PlatformDialog({
  platform,
  open,
  onOpenChange,
  isSaving,
  onSubmit,
}: {
  platform: Platform | null
  open: boolean
  onOpenChange: (open: boolean) => void
  isSaving: boolean
  onSubmit: (form: PlatformForm) => void
}) {
  const [form, setForm] = useState<PlatformForm>(
    platform
      ? {
          name: platform.name,
          code: platform.code,
          is_active: platform.is_active,
        }
      : emptyForm
  )
  const update = (patch: Partial<PlatformForm>) =>
    setForm((current) => ({ ...current, ...patch }))
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{platform ? '编辑平台' : '新建平台'}</DialogTitle>
          <DialogDescription>
            平台编码用于资源隔离标识，建议创建后谨慎修改。
          </DialogDescription>
        </DialogHeader>
        <div className='grid gap-4'>
          <Field label='名称'>
            <Input
              value={form.name}
              onChange={(event) => update({ name: event.target.value })}
            />
          </Field>
          <Field label='编码'>
            <Input
              value={form.code}
              placeholder='acme'
              onChange={(event) => update({ code: event.target.value })}
            />
          </Field>
          {platform && (
            <div className='flex items-center justify-between rounded-md border p-3'>
              <Label>启用平台</Label>
              <Switch
                checked={form.is_active}
                onCheckedChange={(is_active) => update({ is_active })}
              />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button
            onClick={() => onSubmit(form)}
            disabled={isSaving || !form.name.trim() || !form.code.trim()}
          >
            {isSaving ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className='grid gap-1.5'>
      <Label>{label}</Label>
      {children}
    </div>
  )
}
