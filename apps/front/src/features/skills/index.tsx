import { useState, type ChangeEvent, type ReactNode } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bot,
  Code2,
  Edit,
  Eye,
  PackageOpen,
  Plus,
  RefreshCw,
  Server,
  ShieldCheck,
  Trash2,
  Upload,
} from 'lucide-react'
import { toast } from 'sonner'
import { listAgents, type Agent } from '@/api/agent'
import { listPlatforms } from '@/api/platform'
import {
  bindSkill,
  createSkill,
  deleteSkill,
  getSkillPackage,
  importSkillPackage,
  listSkillScriptExecutions,
  listAgentSkills,
  listSkillPackages,
  listSkills,
  unbindSkill,
  updateSkillPackage,
  updateSkill,
  type Skill,
  type SkillInput,
  type SkillPackage,
} from '@/api/skills'
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

const skillSchema = z.object({
  name: z.string().min(1, '请输入名称').max(120),
  slug: z
    .string()
    .min(2, '至少 2 个字符')
    .regex(/^[a-z0-9][a-z0-9_-]*$/, '只允许小写字母、数字、下划线和短横线'),
  description: z.string().max(500).optional(),
  instruction_template: z.string().min(1, '请输入指令模板'),
  parameter_schema: z.string().refine(parseJson, '请输入合法 JSON 对象'),
  lifecycle_hooks: z.string().refine(parseJson, '请输入合法 JSON 对象'),
  is_active: z.boolean(),
})
type SkillForm = z.infer<typeof skillSchema>

export function SkillsPage() {
  const queryClient = useQueryClient()
  const [platformId, setPlatformId] = useState<number>()
  const [editing, setEditing] = useState<Skill | null | undefined>()
  const [deleting, setDeleting] = useState<Skill | null>(null)
  const [bindingSkill, setBindingSkill] = useState<Skill | null>(null)
  const [detailPackageId, setDetailPackageId] = useState<number>()
  const platformsQuery = useQuery({
    queryKey: ['platforms'],
    queryFn: listPlatforms,
  })
  const activePlatformId = platformId ?? platformsQuery.data?.[0]?.id
  const skillsQuery = useQuery({
    queryKey: ['skills', activePlatformId],
    queryFn: () => listSkills(activePlatformId!),
    enabled: activePlatformId != null,
  })
  const packagesQuery = useQuery({
    queryKey: ['skill-packages', activePlatformId],
    queryFn: () => listSkillPackages(activePlatformId!),
    enabled: activePlatformId != null,
  })
  const packageDetailQuery = useQuery({
    queryKey: ['skill-package', activePlatformId, detailPackageId],
    queryFn: () => getSkillPackage(activePlatformId!, detailPackageId!),
    enabled: activePlatformId != null && detailPackageId != null,
  })
  const executionsQuery = useQuery({
    queryKey: ['skill-script-executions', activePlatformId],
    queryFn: () => listSkillScriptExecutions(activePlatformId!),
    enabled: activePlatformId != null,
  })
  const invalidateSkills = () =>
    queryClient.invalidateQueries({ queryKey: ['skills', activePlatformId] })
  const invalidatePackages = () =>
    queryClient.invalidateQueries({
      queryKey: ['skill-packages', activePlatformId],
    })
  const saveMutation = useMutation({
    mutationFn: (values: SkillForm) => {
      if (!activePlatformId) throw new Error('请选择平台')
      const input: SkillInput = {
        ...values,
        parameter_schema: JSON.parse(values.parameter_schema),
        lifecycle_hooks: JSON.parse(values.lifecycle_hooks),
      }
      if (editing) {
        const { slug: _slug, ...updateInput } = input
        return updateSkill(activePlatformId, editing.id, {
          ...updateInput,
          is_active: values.is_active,
        })
      }
      return createSkill(activePlatformId, input)
    },
    onSuccess: async () => {
      toast.success(editing ? '技能已更新' : '技能已创建')
      setEditing(undefined)
      await invalidateSkills()
    },
  })
  const statusMutation = useMutation({
    mutationFn: ({ skill, is_active }: { skill: Skill; is_active: boolean }) =>
      updateSkill(activePlatformId!, skill.id, {
        name: skill.name,
        description: skill.description ?? undefined,
        instruction_template: skill.instruction_template,
        parameter_schema: skill.parameter_schema,
        lifecycle_hooks: skill.lifecycle_hooks,
        is_active,
      }),
    onSuccess: async () => {
      toast.success('状态已更新')
      await invalidateSkills()
    },
  })
  const deleteMutation = useMutation({
    mutationFn: (skill: Skill) => deleteSkill(activePlatformId!, skill.id),
    onSuccess: async () => {
      toast.success('技能及绑定已删除')
      setDeleting(null)
      await invalidateSkills()
    },
  })
  const importMutation = useMutation({
    mutationFn: (file: File) => {
      if (!activePlatformId) throw new Error('请选择平台')
      return importSkillPackage(activePlatformId, file)
    },
    onSuccess: async (result) => {
      toast.success(`技能包已导入：${result.package.name}`)
      await invalidateSkills()
      await invalidatePackages()
    },
  })
  const packageMutation = useMutation({
    mutationFn: ({
      skillPackage,
      allow_script_execution,
    }: {
      skillPackage: SkillPackage
      allow_script_execution: boolean
    }) =>
      updateSkillPackage(activePlatformId!, skillPackage.id, {
        allow_script_execution,
      }),
    onSuccess: async () => {
      toast.success('脚本权限已更新')
      await invalidatePackages()
    },
  })
  const handlePackageUpload = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    importMutation.mutate(file)
  }
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
            <h2 className='text-2xl font-bold tracking-tight'>技能管理</h2>
            <p className='text-muted-foreground'>
              配置可复用的指令能力，并绑定到智能体。
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <Select
              value={activePlatformId?.toString()}
              onValueChange={(value) => setPlatformId(Number(value))}
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
              onClick={() => skillsQuery.refetch()}
              disabled={!activePlatformId || skillsQuery.isFetching}
            >
              <RefreshCw className='size-4' />
              刷新
            </Button>
            <Button
              variant='outline'
              size='sm'
              asChild
              disabled={!activePlatformId || importMutation.isPending}
            >
              <label>
                <Upload className='size-4' />
                {importMutation.isPending ? '导入中...' : '导入 Zip'}
                <Input
                  type='file'
                  accept='.zip,application/zip'
                  className='hidden'
                  onChange={handlePackageUpload}
                  disabled={!activePlatformId || importMutation.isPending}
                />
              </label>
            </Button>
            <Button
              size='sm'
              onClick={() => setEditing(null)}
              disabled={!activePlatformId}
            >
              <Plus className='size-4' />
              新建技能
            </Button>
          </div>
        </div>
        <div className='rounded-md border bg-muted/30 px-4 py-3 text-sm'>
          <Server className='me-2 inline size-4' />
          当前平台：{selectedPlatform?.name ?? '未选择平台'}
        </div>
        <div className='overflow-hidden rounded-md border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>技能</TableHead>
                <TableHead>描述</TableHead>
                <TableHead>模板</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className='w-36 text-end'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {skillsQuery.isLoading
                ? Array.from({ length: 5 }).map((_, i) => (
                    <TableRow key={i}>
                      <TableCell colSpan={5}>
                        <Skeleton className='h-8 w-full' />
                      </TableCell>
                    </TableRow>
                  ))
                : (skillsQuery.data?.items ?? []).map((skill) => (
                    <TableRow key={skill.id}>
                      <TableCell>
                        <div className='flex items-center gap-3'>
                          <div className='flex size-9 items-center justify-center rounded-md bg-muted'>
                            <Code2 className='size-4 text-muted-foreground' />
                          </div>
                          <div>
                            <div className='font-medium'>{skill.name}</div>
                            <div className='text-xs text-muted-foreground'>
                              {skill.slug} · ID {skill.id}
                            </div>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className='max-w-56 truncate'>
                        {skill.description || '-'}
                      </TableCell>
                      <TableCell className='max-w-72 truncate font-mono text-xs'>
                        {skill.instruction_template}
                      </TableCell>
                      <TableCell>
                        <div className='flex items-center gap-2'>
                          <Switch
                            checked={skill.is_active}
                            disabled={statusMutation.isPending}
                            onCheckedChange={(is_active) =>
                              statusMutation.mutate({ skill, is_active })
                            }
                          />
                          <Badge
                            variant={skill.is_active ? 'default' : 'secondary'}
                          >
                            {skill.is_active ? '启用' : '停用'}
                          </Badge>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className='flex justify-end gap-1'>
                          <Button
                            size='icon'
                            variant='ghost'
                            onClick={() => setBindingSkill(skill)}
                          >
                            <Bot className='size-4' />
                            <span className='sr-only'>绑定智能体</span>
                          </Button>
                          <Button
                            size='icon'
                            variant='ghost'
                            onClick={() => setEditing(skill)}
                          >
                            <Edit className='size-4' />
                            <span className='sr-only'>编辑</span>
                          </Button>
                          <Button
                            size='icon'
                            variant='ghost'
                            className='text-destructive hover:text-destructive'
                            onClick={() => setDeleting(skill)}
                          >
                            <Trash2 className='size-4' />
                            <span className='sr-only'>删除</span>
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
              {!skillsQuery.isLoading && !skillsQuery.data?.items.length && (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className='h-24 text-center text-muted-foreground'
                  >
                    暂无技能
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
        <div className='overflow-hidden rounded-md border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>脚本</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>退出码</TableHead>
                <TableHead>耗时</TableHead>
                <TableHead>错误</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {executionsQuery.isLoading
                ? Array.from({ length: 2 }).map((_, i) => (
                    <TableRow key={i}>
                      <TableCell colSpan={5}>
                        <Skeleton className='h-8 w-full' />
                      </TableCell>
                    </TableRow>
                  ))
                : (executionsQuery.data?.items ?? []).map((execution) => (
                    <TableRow key={execution.id}>
                      <TableCell className='font-mono text-xs'>
                        {execution.script_path}
                        <div className='text-muted-foreground'>
                          #{execution.id}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            execution.status === 'succeeded'
                              ? 'default'
                              : 'secondary'
                          }
                        >
                          {execution.status}
                        </Badge>
                      </TableCell>
                      <TableCell>{execution.exit_code ?? '-'}</TableCell>
                      <TableCell>
                        {execution.duration_ms != null
                          ? `${execution.duration_ms} ms`
                          : '-'}
                      </TableCell>
                      <TableCell className='max-w-72 truncate text-sm text-muted-foreground'>
                        {execution.error || execution.stderr || '-'}
                      </TableCell>
                    </TableRow>
                  ))}
              {!executionsQuery.isLoading &&
                !executionsQuery.data?.items.length && (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className='h-20 text-center text-muted-foreground'
                    >
                      暂无脚本执行记录
                    </TableCell>
                  </TableRow>
                )}
            </TableBody>
          </Table>
        </div>
        <div className='text-sm text-muted-foreground'>
          共 {skillsQuery.data?.total ?? 0} 个技能
        </div>
        <div className='overflow-hidden rounded-md border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>技能包</TableHead>
                <TableHead>文件</TableHead>
                <TableHead>警告</TableHead>
                <TableHead>脚本权限</TableHead>
                <TableHead className='w-16 text-end'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {packagesQuery.isLoading
                ? Array.from({ length: 3 }).map((_, i) => (
                    <TableRow key={i}>
                      <TableCell colSpan={5}>
                        <Skeleton className='h-8 w-full' />
                      </TableCell>
                    </TableRow>
                  ))
                : (packagesQuery.data?.items ?? []).map((skillPackage) => (
                    <TableRow key={skillPackage.id}>
                      <TableCell>
                        <div className='flex items-center gap-3'>
                          <div className='flex size-9 items-center justify-center rounded-md bg-muted'>
                            <PackageOpen className='size-4 text-muted-foreground' />
                          </div>
                          <div>
                            <div className='font-medium'>
                              {skillPackage.name}
                            </div>
                            <div className='text-xs text-muted-foreground'>
                              {skillPackage.slug} · {skillPackage.package_type}
                            </div>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className='text-end'>
                        <Button
                          size='icon'
                          variant='ghost'
                          title='查看技能包内容'
                          onClick={() => setDetailPackageId(skillPackage.id)}
                        >
                          <Eye className='size-4' />
                          <span className='sr-only'>查看技能包内容</span>
                        </Button>
                      </TableCell>
                      <TableCell className='max-w-56 truncate text-sm text-muted-foreground'>
                        {skillPackage.source_filename}
                      </TableCell>
                      <TableCell className='max-w-72 truncate text-sm text-muted-foreground'>
                        {skillPackage.warnings?.join('；') || '-'}
                      </TableCell>
                      <TableCell>
                        <div className='flex items-center gap-2'>
                          <Switch
                            checked={skillPackage.allow_script_execution}
                            disabled={packageMutation.isPending}
                            onCheckedChange={(allow_script_execution) =>
                              packageMutation.mutate({
                                skillPackage,
                                allow_script_execution,
                              })
                            }
                          />
                          <Badge
                            variant={
                              skillPackage.allow_script_execution
                                ? 'default'
                                : 'secondary'
                            }
                          >
                            <ShieldCheck className='me-1 size-3' />
                            {skillPackage.allow_script_execution
                              ? '允许'
                              : '禁止'}
                          </Badge>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
              {!packagesQuery.isLoading &&
                !packagesQuery.data?.items.length && (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className='h-20 text-center text-muted-foreground'
                    >
                      暂无技能包
                    </TableCell>
                  </TableRow>
                )}
            </TableBody>
          </Table>
        </div>
      </Main>
      <SkillDialog
        key={editing?.id ?? 'new'}
        skill={editing && editing.id ? editing : null}
        open={editing !== undefined}
        onOpenChange={(open) => !open && setEditing(undefined)}
        isSaving={saveMutation.isPending}
        onSubmit={(values) => saveMutation.mutate(values)}
      />
      <Dialog
        open={detailPackageId != null}
        onOpenChange={(open) => !open && setDetailPackageId(undefined)}
      >
        <DialogContent className='max-h-[85vh] max-w-3xl overflow-y-auto'>
          <DialogHeader>
            <DialogTitle>
              {packageDetailQuery.data?.name ?? '技能包详情'}
            </DialogTitle>
            <DialogDescription>
              {packageDetailQuery.data?.source_filename ?? '正在加载技能包内容'}
            </DialogDescription>
          </DialogHeader>
          {packageDetailQuery.isLoading ? (
            <div className='space-y-3 py-2'>
              <Skeleton className='h-20 w-full' />
              <Skeleton className='h-40 w-full' />
            </div>
          ) : (
            <div className='space-y-6'>
              <section>
                <h3 className='mb-2 text-sm font-semibold'>包含的技能</h3>
                <div className='overflow-hidden rounded-md border'>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>名称</TableHead>
                        <TableHead>入口文件</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(packageDetailQuery.data?.skills ?? []).map((skill) => (
                        <TableRow key={skill.id}>
                          <TableCell>
                            <div className='font-medium'>{skill.name}</div>
                            <div className='text-xs text-muted-foreground'>
                              {skill.slug}
                            </div>
                          </TableCell>
                          <TableCell className='font-mono text-xs'>
                            {skill.package_skill_path ?? 'SKILL.md'}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </section>
              <section>
                <div className='mb-2 flex items-center justify-between gap-3'>
                  <h3 className='text-sm font-semibold'>包文件</h3>
                  <span className='text-xs text-muted-foreground'>
                    {packageDetailQuery.data?.files?.length ?? 0} 个文件
                  </span>
                </div>
                <div className='max-h-72 overflow-auto rounded-md border'>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>路径</TableHead>
                        <TableHead className='w-24'>类型</TableHead>
                        <TableHead className='w-24 text-end'>大小</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(packageDetailQuery.data?.files ?? []).map((file) => (
                        <TableRow key={file.id}>
                          <TableCell className='font-mono text-xs'>
                            {file.relative_path}
                          </TableCell>
                          <TableCell>
                            <Badge variant='outline'>{file.role}</Badge>
                          </TableCell>
                          <TableCell className='text-end text-xs text-muted-foreground'>
                            {formatBytes(file.size_bytes)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </section>
            </div>
          )}
        </DialogContent>
      </Dialog>
      {activePlatformId && bindingSkill && (
        <BindingDialog
          platformId={activePlatformId}
          skill={bindingSkill}
          open
          onOpenChange={(open) => !open && setBindingSkill(null)}
        />
      )}
      <AlertDialog
        open={!!deleting}
        onOpenChange={(open) => !open && setDeleting(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>硬删除技能</AlertDialogTitle>
            <AlertDialogDescription>
              确认删除 {deleting?.name}？所有智能体绑定也会永久删除。
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
    </>
  )
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function SkillDialog({
  skill,
  open,
  onOpenChange,
  isSaving,
  onSubmit,
}: {
  skill: Skill | null
  open: boolean
  onOpenChange: (open: boolean) => void
  isSaving: boolean
  onSubmit: (values: SkillForm) => void
}) {
  const [isActive, setIsActive] = useState(skill?.is_active ?? true)
  const form = useForm<SkillForm>({
    resolver: zodResolver(skillSchema),
    values: {
      name: skill?.name ?? '',
      slug: skill?.slug ?? '',
      description: skill?.description ?? '',
      instruction_template:
        skill?.instruction_template ?? '你是一个{{ role }}助手。',
      parameter_schema: JSON.stringify(skill?.parameter_schema ?? {}, null, 2),
      lifecycle_hooks: JSON.stringify(skill?.lifecycle_hooks ?? {}, null, 2),
      is_active: skill?.is_active ?? true,
    },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-h-[90vh] max-w-3xl overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>{skill ? '编辑技能' : '新建技能'}</DialogTitle>
          <DialogDescription>
            模板会在服务端沙箱中渲染，JSON 字段必须是对象。
          </DialogDescription>
        </DialogHeader>
        <form
          id='skill-form'
          onSubmit={form.handleSubmit(onSubmit)}
          className='grid gap-4 sm:grid-cols-2'
        >
          <Field label='名称' error={form.formState.errors.name?.message}>
            <Input {...form.register('name')} />
          </Field>
          <Field label='Slug' error={form.formState.errors.slug?.message}>
            <Input disabled={!!skill} {...form.register('slug')} />
          </Field>
          <Field
            label='描述'
            error={form.formState.errors.description?.message}
          >
            <Input {...form.register('description')} />
          </Field>
          <div className='sm:col-span-2'>
            <Label>指令模板</Label>
            <Textarea
              rows={6}
              className='font-mono text-sm'
              {...form.register('instruction_template')}
            />
            <p className='mt-1 text-xs text-destructive'>
              {form.formState.errors.instruction_template?.message}
            </p>
          </div>
          <div>
            <Label>参数 Schema JSON</Label>
            <Textarea
              rows={8}
              className='font-mono text-sm'
              {...form.register('parameter_schema')}
            />
            <p className='mt-1 text-xs text-destructive'>
              {form.formState.errors.parameter_schema?.message}
            </p>
          </div>
          <div>
            <Label>Lifecycle Hooks JSON</Label>
            <Textarea
              rows={8}
              className='font-mono text-sm'
              {...form.register('lifecycle_hooks')}
            />
            <p className='mt-1 text-xs text-destructive'>
              {form.formState.errors.lifecycle_hooks?.message}
            </p>
          </div>
          {skill && (
            <div className='flex items-center justify-between rounded-md border p-3 sm:col-span-2'>
              <Label>启用技能</Label>
              <Switch
                checked={isActive}
                onCheckedChange={(value) => {
                  setIsActive(value)
                  form.setValue('is_active', value)
                }}
              />
            </div>
          )}
        </form>
        <DialogFooter>
          <Button type='submit' form='skill-form' disabled={isSaving}>
            {isSaving ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Field({
  label,
  error,
  children,
}: {
  label: string
  error?: string
  children: ReactNode
}) {
  return (
    <div>
      <Label>{label}</Label>
      {children}
      <p className='mt-1 text-xs text-destructive'>{error}</p>
    </div>
  )
}

function BindingDialog({
  platformId,
  skill,
  open,
  onOpenChange,
}: {
  platformId: number
  skill: Skill
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [agentId, setAgentId] = useState<number>()
  const agentsQuery = useQuery({
    queryKey: ['agents', platformId],
    queryFn: () => listAgents(platformId),
    enabled: open,
  })
  const bindingQuery = useQuery({
    queryKey: ['agent-skills', platformId, agentId],
    queryFn: () => listAgentSkills(platformId, agentId!),
    enabled: agentId != null,
  })
  const bindMutation = useMutation({
    mutationFn: () => bindSkill(platformId, agentId!, skill.id),
    onSuccess: async () => {
      toast.success('技能已绑定')
      await queryClient.invalidateQueries({
        queryKey: ['agent-skills', platformId, agentId],
      })
    },
  })
  const unbindMutation = useMutation({
    mutationFn: () => unbindSkill(platformId, agentId!, skill.id),
    onSuccess: async () => {
      toast.success('技能已解绑')
      await queryClient.invalidateQueries({
        queryKey: ['agent-skills', platformId, agentId],
      })
    },
  })
  const bound = bindingQuery.data?.some((item) => item.skill_id === skill.id)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{skill.name} · 绑定智能体</DialogTitle>
          <DialogDescription>停用技能不会解除现有绑定。</DialogDescription>
        </DialogHeader>
        <Select
          value={agentId?.toString()}
          onValueChange={(value) => setAgentId(Number(value))}
        >
          <SelectTrigger>
            <SelectValue placeholder='选择智能体' />
          </SelectTrigger>
          <SelectContent>
            {(agentsQuery.data?.items ?? []).map((agent: Agent) => (
              <SelectItem key={agent.id} value={agent.id.toString()}>
                {agent.name} ({agent.slug})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {agentId && (
          <div className='rounded-md border p-3 text-sm'>
            {bindingQuery.isLoading ? (
              '读取绑定中...'
            ) : bound ? (
              <div className='flex items-center justify-between'>
                <span>当前已绑定</span>
                <Button
                  variant='outline'
                  size='sm'
                  onClick={() => unbindMutation.mutate()}
                  disabled={unbindMutation.isPending}
                >
                  解绑
                </Button>
              </div>
            ) : (
              <div className='flex items-center justify-between'>
                <span>当前未绑定</span>
                <Button
                  size='sm'
                  onClick={() => bindMutation.mutate()}
                  disabled={bindMutation.isPending}
                >
                  绑定
                </Button>
              </div>
            )}
          </div>
        )}
        <DialogFooter>
          <Button variant='outline' onClick={() => onOpenChange(false)}>
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function parseJson(value: string) {
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
  } catch {
    return false
  }
}
