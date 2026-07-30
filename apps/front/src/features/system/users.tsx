import { useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Edit, Plus, RefreshCw, Search, Trash2, UserRound } from 'lucide-react'
import { toast } from 'sonner'
import { getUserRoles, type UserRole } from '@/api/role'
import {
  createSystemUser,
  deleteSystemUser,
  getSystemUsers,
  updateSystemUser,
  type CreateUserInput,
  type SystemUser,
  type UpdateUserInput,
} from '@/api/user'
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
import { Checkbox } from '@/components/ui/checkbox'
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
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { PasswordInput } from '@/components/password-input'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { ThemeSwitch } from '@/components/theme-switch'

const PAGE_SIZE = 10

const userFormSchema = z
  .object({
    name: z.string().min(1, '请输入姓名').max(100),
    account: z.string().min(3, '账号至少 3 个字符').max(255),
    email: z.email('请输入正确的邮箱'),
    password: z.string(),
    is_active: z.boolean(),
    role_ids: z.array(z.number()),
    isEdit: z.boolean(),
  })
  .refine(({ isEdit, password }) => isEdit || password.length >= 6, {
    message: '密码至少 6 个字符',
    path: ['password'],
  })

type UserForm = z.infer<typeof userFormSchema>

type SystemUsersPageProps = {
  search: {
    page?: number
    pageSize?: number
    name?: string
    email?: string
  }
  navigate: (opts: {
    search: (prev: Record<string, unknown>) => Record<string, unknown>
    replace?: boolean
  }) => void
}

export function SystemUsersPage({ search, navigate }: SystemUsersPageProps) {
  const queryClient = useQueryClient()
  const [nameKeyword, setNameKeyword] = useState(search.name ?? '')
  const [emailKeyword, setEmailKeyword] = useState(search.email ?? '')
  const [editingUser, setEditingUser] = useState<SystemUser | null>(null)
  const [isDialogOpen, setIsDialogOpen] = useState(false)
  const [deletingUser, setDeletingUser] = useState<SystemUser | null>(null)

  const page = search.page ?? 1
  const pageSize = search.pageSize ?? PAGE_SIZE
  const usersQuery = useQuery({
    queryKey: ['system', 'users', { page, pageSize, ...search }],
    queryFn: () => getSystemUsers({ page, pageSize, ...search }),
  })
  const rolesQuery = useQuery({
    queryKey: ['system', 'user-roles'],
    queryFn: () => getUserRoles(),
    staleTime: 60_000,
  })

  const saveMutation = useMutation({
    mutationFn: (values: UserForm) => {
      if (editingUser) {
        const payload: UpdateUserInput = {
          name: values.name,
          email: values.email,
          account: values.account,
          is_active: values.is_active,
          role_ids: values.role_ids,
        }
        return updateSystemUser(editingUser.id, payload)
      }
      const payload: CreateUserInput = {
        name: values.name,
        email: values.email,
        account: values.account,
        password: values.password,
        role_ids: values.role_ids,
      }
      return createSystemUser(payload)
    },
    onSuccess: async () => {
      toast.success(editingUser ? '用户已更新' : '用户已创建')
      setIsDialogOpen(false)
      setEditingUser(null)
      await queryClient.invalidateQueries({ queryKey: ['system', 'users'] })
    },
  })

  const statusMutation = useMutation({
    mutationFn: ({
      user,
      is_active,
    }: {
      user: SystemUser
      is_active: boolean
    }) => updateSystemUser(user.id, { is_active }),
    onSuccess: async () => {
      toast.success('用户状态已更新')
      await queryClient.invalidateQueries({ queryKey: ['system', 'users'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteSystemUser(id),
    onSuccess: async () => {
      toast.success('用户已删除')
      setDeletingUser(null)
      await queryClient.invalidateQueries({ queryKey: ['system', 'users'] })
    },
  })

  const pageData = usersQuery.data
  const totalPage = Math.max(pageData?.totalPage ?? 1, 1)
  const updateSearch = (patch: Record<string, unknown>) => {
    navigate({ search: (prev) => ({ ...prev, ...patch }) })
  }

  const submitSearch = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    updateSearch({
      page: undefined,
      name: nameKeyword.trim() || undefined,
      email: emailKeyword.trim() || undefined,
    })
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
            <h2 className='text-2xl font-bold tracking-tight'>用户管理</h2>
            <p className='text-muted-foreground'>管理用户资料、状态和角色。</p>
          </div>
          <div className='flex items-center gap-2'>
            <Button
              variant='outline'
              size='sm'
              onClick={() => usersQuery.refetch()}
              disabled={usersQuery.isFetching}
            >
              <RefreshCw className='me-2 size-4' />
              刷新
            </Button>
            <Button
              size='sm'
              onClick={() => {
                setEditingUser(null)
                setIsDialogOpen(true)
              }}
            >
              <Plus className='me-2 size-4' />
              新建用户
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
              placeholder='按姓名搜索'
              className='ps-9'
            />
          </div>
          <Input
            value={emailKeyword}
            onChange={(event) => setEmailKeyword(event.target.value)}
            placeholder='按邮箱搜索'
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
                <TableHead>用户</TableHead>
                <TableHead>邮箱</TableHead>
                <TableHead>角色</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className='w-32 text-end'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {usersQuery.isLoading ? (
                Array.from({ length: 5 }).map((_, index) => (
                  <TableRow key={index}>
                    <TableCell colSpan={5}>
                      <Skeleton className='h-8 w-full' />
                    </TableCell>
                  </TableRow>
                ))
              ) : pageData?.items.length ? (
                pageData.items.map((user) => (
                  <TableRow key={user.id}>
                    <TableCell>
                      <div className='flex items-center gap-3'>
                        <div className='flex size-9 items-center justify-center rounded-md bg-muted'>
                          <UserRound className='size-4 text-muted-foreground' />
                        </div>
                        <div>
                          <div className='font-medium'>{user.name}</div>
                          <div className='text-xs text-muted-foreground'>
                            @{user.account} · ID {user.id}
                          </div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>{user.email}</TableCell>
                    <TableCell>
                      <div className='flex flex-wrap gap-1'>
                        {user.roles.length ? (
                          user.roles.map((role) => (
                            <Badge key={role.id} variant='outline'>
                              {role.name}
                            </Badge>
                          ))
                        ) : (
                          <span className='text-muted-foreground'>未分配</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className='flex items-center gap-2'>
                        <Switch
                          checked={user.is_active}
                          disabled={statusMutation.isPending}
                          onCheckedChange={(is_active) =>
                            statusMutation.mutate({ user, is_active })
                          }
                        />
                        <span className='text-sm'>
                          {user.is_active ? '启用' : '停用'}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className='text-end'>
                      <div className='flex justify-end gap-2'>
                        <Button
                          size='icon'
                          variant='ghost'
                          onClick={() => {
                            setEditingUser(user)
                            setIsDialogOpen(true)
                          }}
                        >
                          <Edit className='size-4' />
                          <span className='sr-only'>编辑</span>
                        </Button>
                        <Button
                          size='icon'
                          variant='ghost'
                          className='text-destructive hover:text-destructive'
                          onClick={() => setDeletingUser(user)}
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
                  <TableCell colSpan={5} className='h-24 text-center'>
                    暂无用户数据
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
              disabled={page <= 1 || usersQuery.isFetching}
              onClick={() => updateSearch({ page: page - 1 })}
            >
              上一页
            </Button>
            <Button
              variant='outline'
              size='sm'
              disabled={page >= totalPage || usersQuery.isFetching}
              onClick={() => updateSearch({ page: page + 1 })}
            >
              下一页
            </Button>
          </div>
        </div>
      </Main>

      <UserFormDialog
        user={editingUser}
        roles={rolesQuery.data?.items ?? []}
        rolesLoading={rolesQuery.isLoading}
        open={isDialogOpen}
        isSaving={saveMutation.isPending}
        onOpenChange={(open) => {
          setIsDialogOpen(open)
          if (!open) setEditingUser(null)
        }}
        onSubmit={(values) => saveMutation.mutate(values)}
      />
      <AlertDialog
        open={!!deletingUser}
        onOpenChange={(open) => !open && setDeletingUser(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除用户</AlertDialogTitle>
            <AlertDialogDescription>
              确认删除 {deletingUser?.name}？此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() =>
                deletingUser && deleteMutation.mutate(deletingUser.id)
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

type UserFormDialogProps = {
  user: SystemUser | null
  roles: UserRole[]
  rolesLoading: boolean
  open: boolean
  isSaving: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (values: UserForm) => void
}

function UserFormDialog({
  user,
  roles,
  rolesLoading,
  open,
  isSaving,
  onOpenChange,
  onSubmit,
}: UserFormDialogProps) {
  const isEdit = !!user
  const form = useForm<UserForm>({
    resolver: zodResolver(userFormSchema),
    values: {
      name: user?.name ?? '',
      account: user?.account ?? '',
      email: user?.email ?? '',
      password: '',
      is_active: user?.is_active ?? true,
      role_ids: user?.roles.map((role) => role.id) ?? [],
      isEdit,
    },
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-lg'>
        <DialogHeader className='text-start'>
          <DialogTitle>{isEdit ? '编辑用户' : '新建用户'}</DialogTitle>
          <DialogDescription>
            {isEdit ? '更新用户资料、状态和角色。' : '创建用户并分配角色。'}
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            id='system-user-form'
            onSubmit={form.handleSubmit(onSubmit)}
            className='grid max-h-[65vh] gap-4 overflow-y-auto px-1'
          >
            <FormField
              control={form.control}
              name='name'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>姓名</FormLabel>
                  <FormControl>
                    <Input placeholder='张三' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='account'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>账号</FormLabel>
                  <FormControl>
                    <Input placeholder='zhangsan' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='email'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>邮箱</FormLabel>
                  <FormControl>
                    <Input
                      type='email'
                      placeholder='zhangsan@example.com'
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            {!isEdit && (
              <FormField
                control={form.control}
                name='password'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>密码</FormLabel>
                    <FormControl>
                      <PasswordInput placeholder='至少 6 个字符' {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}
            {isEdit && (
              <FormField
                control={form.control}
                name='is_active'
                render={({ field }) => (
                  <FormItem className='flex items-center justify-between rounded-md border p-3'>
                    <FormLabel>启用账号</FormLabel>
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
            <FormField
              control={form.control}
              name='role_ids'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>角色</FormLabel>
                  <div className='grid gap-2 rounded-md border p-3'>
                    {rolesLoading ? (
                      <Skeleton className='h-8 w-full' />
                    ) : roles.length ? (
                      roles.map((role) => (
                        <label
                          key={role.id}
                          className='flex items-center gap-2 text-sm'
                        >
                          <Checkbox
                            checked={field.value.includes(role.id)}
                            onCheckedChange={(checked) =>
                              field.onChange(
                                checked
                                  ? [...field.value, role.id]
                                  : field.value.filter((id) => id !== role.id)
                              )
                            }
                          />
                          <span>{role.name}</span>
                          <span className='text-muted-foreground'>
                            ({role.code})
                          </span>
                        </label>
                      ))
                    ) : (
                      <span className='text-sm text-muted-foreground'>
                        暂无可用角色
                      </span>
                    )}
                  </div>
                  <FormMessage />
                </FormItem>
              )}
            />
          </form>
        </Form>
        <DialogFooter>
          <Button
            type='submit'
            form='system-user-form'
            disabled={isSaving || rolesLoading}
          >
            {isSaving ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
