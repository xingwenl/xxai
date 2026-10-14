import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import { deleteAgent, getAgent, updateAgent } from '@/api/agent'
import { listWorkflows } from '@/api/workflow'
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
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { agentSchema, type AgentForm } from './agent-form-schema'

/** 下拉框不允许空字符串值，用哨兵表示「不绑定」。 */
const NO_WORKFLOW = '__none__'

export function AgentConfigTab({
  platformId,
  agentId,
}: {
  platformId?: number
  agentId: number
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [deleting, setDeleting] = useState(false)
  const agentQuery = useQuery({
    queryKey: ['agent', platformId, agentId],
    queryFn: () => getAgent(platformId!, agentId),
    enabled: platformId != null,
  })
  // 只列当前平台处于 active 的工作流：绑定暂停/跨平台工作流后端会直接拒绝。
  const workflowsQuery = useQuery({
    queryKey: ['workflows', platformId, 'active'],
    queryFn: () =>
      listWorkflows(platformId!, { pageSize: 100, status: 'active' }),
    enabled: platformId != null,
  })
  const agent = agentQuery.data
  const activeWorkflows = workflowsQuery.data?.items ?? []
  const form = useForm<AgentForm>({
    resolver: zodResolver(agentSchema),
    values: {
      name: agent?.name ?? '',
      slug: agent?.slug ?? '',
      description: agent?.description ?? '',
      is_active: agent?.is_active ?? true,
      // 服务端没返回该字段时按「未绑定」渲染，而不是 undefined 让下拉框空白。
      orchestration_workflow_id: agent?.orchestration_workflow_id ?? null,
    },
  })
  // 用 useWatch 而不是 form.watch：后者会被 React Compiler 判定为不可安全缓存。
  const orchestrationId =
    useWatch({ control: form.control, name: 'orchestration_workflow_id' }) ??
    null
  // 当前绑定不在 active 列表里（被暂停 / 删除 / 跨平台）时，单独给一个只读选项。
  const boundWorkflowOutsideList =
    orchestrationId != null &&
    !activeWorkflows.some((workflow) => workflow.id === orchestrationId)
      ? orchestrationId
      : null
  const saveMutation = useMutation({
    mutationFn: (values: AgentForm) =>
      updateAgent(platformId!, agentId, {
        name: values.name,
        slug: values.slug,
        description: values.description,
        is_active: values.is_active,
        // 始终显式带上：null 表示解绑，字段缺失才是「不改动」。
        orchestration_workflow_id: values.orchestration_workflow_id ?? null,
      }),
    onSuccess: async () => {
      toast.success('配置已保存')
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['agent', platformId, agentId],
        }),
        queryClient.invalidateQueries({ queryKey: ['agents', platformId] }),
      ])
    },
  })
  const deleteMutation = useMutation({
    mutationFn: () => deleteAgent(platformId!, agentId),
    onSuccess: () => {
      toast.success('智能体已删除')
      void navigate({ to: '/ai/bots', search: { platform: platformId } })
    },
  })
  const version = agent?.current_version

  return (
    <div className='grid gap-4'>
      <Card className='rounded-md py-4'>
        <CardHeader className='px-4 pb-0'>
          <CardTitle className='text-base'>基本信息</CardTitle>
          <CardDescription>
            名称、描述与启用状态保存后立即生效。
          </CardDescription>
        </CardHeader>
        <CardContent className='px-4 pt-4'>
          <Form {...form}>
            <form
              id='agent-config-form'
              onSubmit={form.handleSubmit((values) =>
                saveMutation.mutate(values)
              )}
              className='grid gap-4'
            >
              <FormField
                control={form.control}
                name='name'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>名称</FormLabel>
                    <FormControl>
                      <Input {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name='slug'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Slug</FormLabel>
                    <FormControl>
                      <Input disabled {...field} />
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
                      <Textarea rows={3} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name='is_active'
                render={({ field }) => (
                  <FormItem className='flex items-center justify-between rounded-md border p-3'>
                    <FormLabel>启用智能体</FormLabel>
                    <FormControl>
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                  </FormItem>
                )}
              />
              <div className='flex justify-end'>
                <Button
                  type='submit'
                  form='agent-config-form'
                  disabled={saveMutation.isPending}
                >
                  {saveMutation.isPending ? '保存中...' : '保存'}
                </Button>
              </div>
            </form>
          </Form>
        </CardContent>
      </Card>

      <Card className='rounded-md py-4'>
        <CardHeader className='px-4 pb-0'>
          <CardTitle className='text-base'>编排绑定</CardTitle>
          <CardDescription>
            绑定一条编排工作流后，该智能体的会话可按这条 DAG
            执行；只能绑定当前平台启用中的工作流。修改后点上方「保存」生效。
          </CardDescription>
        </CardHeader>
        <CardContent className='px-4 pt-4'>
          {workflowsQuery.isLoading ? (
            <Skeleton className='h-10 w-full' />
          ) : (
            <Select
              value={
                orchestrationId == null ? NO_WORKFLOW : String(orchestrationId)
              }
              onValueChange={(value) =>
                form.setValue(
                  'orchestration_workflow_id',
                  value === NO_WORKFLOW ? null : Number(value),
                  { shouldDirty: true }
                )
              }
            >
              <SelectTrigger className='w-full sm:w-96'>
                <SelectValue placeholder='选择编排工作流' />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_WORKFLOW}>不绑定</SelectItem>
                {boundWorkflowOutsideList != null && (
                  // 已绑定的工作流可能被暂停或删除：补一个只读选项，
                  // 否则下拉框会显示空白，用户看不出当前到底绑了什么。
                  <SelectItem value={String(boundWorkflowOutsideList)}>
                    #{boundWorkflowOutsideList}（已暂停或不可用）
                  </SelectItem>
                )}
                {activeWorkflows.map((workflow) => (
                  <SelectItem key={workflow.id} value={String(workflow.id)}>
                    {workflow.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {!workflowsQuery.isLoading && activeWorkflows.length === 0 && (
            <p className='mt-2 text-xs text-muted-foreground'>
              当前平台还没有启用中的工作流，先去工作流页面创建并启用。
            </p>
          )}
        </CardContent>
      </Card>

      <Card className='rounded-md py-4'>
        <CardHeader className='px-4 pb-0'>
          <CardTitle className='text-base'>当前模型配置</CardTitle>
          <CardDescription>
            修改模型与提示词需创建并发布新版本。
          </CardDescription>
        </CardHeader>
        <CardContent className='px-4 pt-3 text-sm'>
          {agentQuery.isLoading ? (
            <Skeleton className='h-20 w-full' />
          ) : version ? (
            <div className='grid gap-1 sm:grid-cols-2'>
              <div>
                版本：<span className='font-medium'>v{version.version}</span>
              </div>
              <div>
                模型：<span className='font-medium'>{version.model_name}</span>
              </div>
              <div>模型地址：{version.model_base_url || '默认'}</div>
              <div>Temperature：{version.temperature}</div>
              <div>API Key：{version.has_api_key ? '已配置' : '未配置'}</div>
              <div>
                发布时间：
                {version.published_at
                  ? new Date(version.published_at).toLocaleString('zh-CN')
                  : '未发布'}
              </div>
            </div>
          ) : (
            <div className='text-muted-foreground'>尚未发布版本。</div>
          )}
        </CardContent>
      </Card>

      <Card className='rounded-md py-4'>
        <CardHeader className='px-4 pb-0'>
          <CardTitle className='text-base'>危险操作</CardTitle>
        </CardHeader>
        <CardContent className='px-4 pt-3'>
          <div className='flex items-center justify-between gap-3 rounded-md border border-destructive/30 px-4 py-3'>
            <div className='text-sm'>
              <div className='font-medium'>删除智能体</div>
              <div className='text-muted-foreground'>
                该智能体及其所有版本将永久删除，无法恢复。
              </div>
            </div>
            <Button
              variant='destructive'
              size='sm'
              onClick={() => setDeleting(true)}
            >
              <AlertTriangle className='me-2 size-4' />
              永久删除
            </Button>
          </div>
        </CardContent>
      </Card>

      <AlertDialog open={deleting} onOpenChange={setDeleting}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>硬删除智能体</AlertDialogTitle>
            <AlertDialogDescription>
              确认删除 {agent?.name ?? '该智能体'}
              ？该智能体及其所有版本将永久删除，无法恢复。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              className='text-destructive-foreground bg-destructive hover:bg-destructive/90'
              onClick={() => deleteMutation.mutate()}
            >
              永久删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
