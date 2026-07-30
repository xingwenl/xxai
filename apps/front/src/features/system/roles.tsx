import { useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Edit, Plus, RefreshCw, Search, Shield, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import {
  createRole,
  deleteRole,
  listRoles,
  updateRole,
  type CreateRoleInput,
  type Role,
  type UpdateRoleInput,
} from '@/api/role'
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
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
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
import { Textarea } from '@/components/ui/textarea'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { ThemeSwitch } from '@/components/theme-switch'

const PAGE_SIZE = 10

const roleFormSchema = z.object({
  code: z.string().min(1, '请输入角色编码').max(100),
  name: z.string().min(1, '请输入角色名称').max(100),
  description: z.string().max(255).optional(),
  is_active: z.boolean(),
})

type RoleForm = z.infer<typeof roleFormSchema>

type SystemRolesPageProps = {
  search: {
    page?: number
    pageSize?: number
    name?: string
    code?: string
  }
  navigate: (opts: {
    search: (prev: Record<string, unknown>) => Record<string, unknown>
    replace?: boolean
  }) => void
}

export function SystemRolesPage({ search, navigate }: SystemRolesPageProps) {
  const queryClient = useQueryClient()
  const [nameKeyword, setNameKeyword] = useState(search.name ?? '')
  const [codeKeyword, setCodeKeyword] = useState(search.code ?? '')
  const [editingRole, setEditingRole] = useState<Role | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [deletingRole, setDeletingRole] = useState<Role | null>(null)
  const page = search.page ?? 1
  const pageSize = search.pageSize ?? PAGE_SIZE

  const rolesQuery = useQuery({
    queryKey: ['system', 'roles', { page, pageSize, ...search }],
    queryFn: () => listRoles({ page, pageSize, ...search }),
  })

  const invalidateRoles = () =>
    queryClient.invalidateQueries({ queryKey: ['system', 'roles'] })

  const saveMutation = useMutation({
    mutationFn: (values: RoleForm) => {
      if (editingRole) {
        const input: UpdateRoleInput = {
          code: values.code,
          name: values.name,
          description: values.description,
          is_active: values.is_active,
        }
        return updateRole(editingRole.id, input)
      }
      const input: CreateRoleInput = {
        code: values.code,
        name: values.name,
        description: values.description,
      }
      return createRole(input)
    },
    onSuccess: async () => {
      toast.success(editingRole ? '角色已更新' : '角色已创建')
      setDialogOpen(false)
      setEditingRole(null)
      await invalidateRoles()
      await queryClient.invalidateQueries({
        queryKey: ['system', 'user-roles'],
      })
    },
  })

  const statusMutation = useMutation({
    mutationFn: ({ role, is_active }: { role: Role; is_active: boolean }) =>
      updateRole(role.id, {
        code: role.code,
        name: role.name,
        description: role.description ?? undefined,
        is_active,
      }),
    onSuccess: async () => {
      toast.success('角色状态已更新')
      await invalidateRoles()
      await queryClient.invalidateQueries({
        queryKey: ['system', 'user-roles'],
      })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteRole(id),
    onSuccess: async () => {
      toast.success('角色已删除')
      setDeletingRole(null)
      await invalidateRoles()
    },
  })

  const updateSearch = (patch: Record<string, unknown>) =>
    navigate({ search: (prev) => ({ ...prev, ...patch }) })
  const submitSearch = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    updateSearch({
      page: undefined,
      name: nameKeyword.trim() || undefined,
      code: codeKeyword.trim() || undefined,
    })
  }
  const pageData = rolesQuery.data
  const totalPage = Math.max(pageData?.totalPage ?? 1, 1)

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
            <h2 className='text-2xl font-bold tracking-tight'>角色管理</h2>
            <p className='text-muted-foreground'>
              管理角色编码、名称、状态和描述。
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <Button
              variant='outline'
              size='sm'
              onClick={() => rolesQuery.refetch()}
              disabled={rolesQuery.isFetching}
            >
              <RefreshCw className='me-2 size-4' />
              刷新
            </Button>
            <Button
              size='sm'
              onClick={() => {
                setEditingRole(null)
                setDialogOpen(true)
              }}
            >
              <Plus className='me-2 size-4' />
              新建角色
            </Button>
          </div>
        </div>
        <form
          className='flex flex-wrap items-center gap-2'
          onSubmit={submitSearch}
        >
          <div className='relative min-w-52 flex-1'>
            <Search className='absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground' />
            <Input
              value={nameKeyword}
              onChange={(event) => setNameKeyword(event.target.value)}
              placeholder='按名称搜索'
              className='ps-9'
            />
          </div>
          <Input
            value={codeKeyword}
            onChange={(event) => setCodeKeyword(event.target.value)}
            placeholder='按编码搜索'
            className='min-w-52 flex-1'
          />
          <Button type='submit' variant='secondary'>
            搜索
          </Button>
        </form>
        <div className='overflow-hidden rounded-md border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>角色</TableHead>
                <TableHead>描述</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className='w-32 text-end'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rolesQuery.isLoading ? (
                Array.from({ length: 5 }).map((_, index) => (
                  <TableRow key={index}>
                    <TableCell colSpan={4}>
                      <Skeleton className='h-8 w-full' />
                    </TableCell>
                  </TableRow>
                ))
              ) : pageData?.items.length ? (
                pageData.items.map((role) => (
                  <TableRow key={role.id}>
                    <TableCell>
                      <div className='flex items-center gap-3'>
                        <div className='flex size-9 items-center justify-center rounded-md bg-muted'>
                          <Shield className='size-4 text-muted-foreground' />
                        </div>
                        <div>
                          <div className='font-medium'>{role.name}</div>
                          <div className='text-xs text-muted-foreground'>
                            {role.code} · ID {role.id}
                          </div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className='max-w-md truncate'>
                      {role.description || '-'}
                    </TableCell>
                    <TableCell>
                      <div className='flex items-center gap-2'>
                        <Switch
                          checked={role.is_active}
                          disabled={statusMutation.isPending}
                          onCheckedChange={(is_active) =>
                            statusMutation.mutate({ role, is_active })
                          }
                        />
                        <Badge
                          variant={role.is_active ? 'default' : 'secondary'}
                        >
                          {role.is_active ? '启用' : '停用'}
                        </Badge>
                      </div>
                    </TableCell>
                    <TableCell className='text-end'>
                      <div className='flex justify-end gap-2'>
                        <Button
                          size='icon'
                          variant='ghost'
                          onClick={() => {
                            setEditingRole(role)
                            setDialogOpen(true)
                          }}
                        >
                          <Edit className='size-4' />
                          <span className='sr-only'>编辑</span>
                        </Button>
                        <Button
                          size='icon'
                          variant='ghost'
                          className='text-destructive hover:text-destructive'
                          onClick={() => setDeletingRole(role)}
                        >
                          <Trash2 className='size-4' />
                          <span className='sr-only'>删除</span>
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={4} className='h-24 text-center'>
                    暂无角色数据
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
              disabled={page <= 1 || rolesQuery.isFetching}
              onClick={() => updateSearch({ page: page - 1 })}
            >
              上一页
            </Button>
            <Button
              variant='outline'
              size='sm'
              disabled={page >= totalPage || rolesQuery.isFetching}
              onClick={() => updateSearch({ page: page + 1 })}
            >
              下一页
            </Button>
          </div>
        </div>
      </Main>
      <RoleFormDialog
        role={editingRole}
        open={dialogOpen}
        isSaving={saveMutation.isPending}
        onOpenChange={(open) => {
          setDialogOpen(open)
          if (!open) setEditingRole(null)
        }}
        onSubmit={(values) => saveMutation.mutate(values)}
      />
      <AlertDialog
        open={!!deletingRole}
        onOpenChange={(open) => !open && setDeletingRole(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除角色</AlertDialogTitle>
            <AlertDialogDescription>
              确认删除角色 {deletingRole?.name}
              ？如果角色仍被用户使用，后端会拒绝删除。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() =>
                deletingRole && deleteMutation.mutate(deletingRole.id)
              }
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

function RoleFormDialog({
  role,
  open,
  isSaving,
  onOpenChange,
  onSubmit,
}: {
  role: Role | null
  open: boolean
  isSaving: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (values: RoleForm) => void
}) {
  const form = useForm<RoleForm>({
    resolver: zodResolver(roleFormSchema),
    values: {
      code: role?.code ?? '',
      name: role?.name ?? '',
      description: role?.description ?? '',
      is_active: role?.is_active ?? true,
    },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-lg'>
        <DialogHeader className='text-start'>
          <DialogTitle>{role ? '编辑角色' : '新建角色'}</DialogTitle>
          <DialogDescription>
            角色编码用于程序识别，角色名称用于界面展示。
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            id='system-role-form'
            onSubmit={form.handleSubmit(onSubmit)}
            className='grid gap-4'
          >
            <FormField
              control={form.control}
              name='code'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>角色编码</FormLabel>
                  <FormControl>
                    <Input disabled={!!role} placeholder='admin' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='name'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>角色名称</FormLabel>
                  <FormControl>
                    <Input placeholder='管理员' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='description'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>描述</FormLabel>
                  <FormControl>
                    <Textarea rows={3} placeholder='描述角色职责' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            {role && (
              <FormField
                control={form.control}
                name='is_active'
                render={({ field }) => (
                  <FormItem className='flex items-center justify-between rounded-md border p-3'>
                    <FormLabel>启用角色</FormLabel>
                    <FormControl>
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                  </FormItem>
                )}
              />
            )}
          </form>
        </Form>
        <DialogFooter>
          <Button type='submit' form='system-role-form' disabled={isSaving}>
            {isSaving ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
