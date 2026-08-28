import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { createAgentVersion, type AgentVersionInput } from '@/api/agent'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'

export const versionSchema = z.object({
  system_prompt: z.string().min(1, '请输入系统提示词'),
  model_name: z.string().min(1, '请输入模型名称').max(120),
  model_base_url: z.string().url('请输入有效 URL').optional().or(z.literal('')),
  api_key: z.string().optional(),
  temperature: z.coerce.number().min(0).max(2),
  capabilities_enabled: z.boolean().optional(),
  capabilities: z.object({
    image: z.boolean(),
    native_file: z.boolean(),
    text_retrieval: z.boolean(),
  }),
})

type VersionFormInput = z.input<typeof versionSchema>
type VersionForm = z.output<typeof versionSchema>

const CAPABILITY_FIELDS: Array<{
  key: 'image' | 'native_file' | 'text_retrieval'
  label: string
  hint: string
}> = [
  {
    key: 'image',
    label: '支持视觉输入',
    hint: '图片可直接以 image_url 内容块发送给模型',
  },
  {
    key: 'native_file',
    label: '支持原生文件输入',
    hint: '文档可优先发送原始文件而非文本检索结果',
  },
  {
    key: 'text_retrieval',
    label: '支持文本检索注入',
    hint: '按问题检索附件切块后注入上下文，几乎全部文本模型都具备',
  },
]

export function AgentVersionForm({
  platformId,
  agentId,
  onCreated,
}: {
  platformId?: number
  agentId: number
  onCreated: () => void
}) {
  const queryClient = useQueryClient()
  const form = useForm<VersionFormInput, unknown, VersionForm>({
    resolver: zodResolver(versionSchema),
    defaultValues: {
      system_prompt: '',
      model_name: 'gpt-4o-mini',
      model_base_url: '',
      api_key: '',
      temperature: 0.2,
      capabilities_enabled: false,
      capabilities: {
        image: false,
        native_file: false,
        text_retrieval: true,
      },
    },
  })
  // eslint-disable-next-line react-hooks/incompatible-library
  const capabilitiesEnabled = form.watch('capabilities_enabled')
  const mutation = useMutation({
    mutationFn: (values: VersionForm) => {
      const input: AgentVersionInput = {
        system_prompt: values.system_prompt,
        model_name: values.model_name,
        model_base_url: values.model_base_url || undefined,
        api_key: values.api_key || undefined,
        temperature: values.temperature,
        model_options: {},
        capabilities: values.capabilities_enabled
          ? values.capabilities
          : undefined,
      }
      return createAgentVersion(platformId!, agentId, input)
    },
    onSuccess: async () => {
      toast.success('版本已创建')
      form.reset()
      await queryClient.invalidateQueries({
        queryKey: ['agent-versions', platformId, agentId],
      })
      onCreated()
    },
  })
  return (
    <Form {...form}>
      <form
        id='agent-version-form'
        onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
        className='grid gap-4'
      >
        <FormField
          control={form.control}
          name='model_name'
          render={({ field }) => (
            <FormItem>
              <FormLabel>模型名称</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name='model_base_url'
          render={({ field }) => (
            <FormItem>
              <FormLabel>模型地址</FormLabel>
              <FormControl>
                <Input
                  placeholder='可选，例如 https://api.openai.com/v1'
                  {...field}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name='api_key'
          render={({ field }) => (
            <FormItem>
              <FormLabel>API Key</FormLabel>
              <FormControl>
                <Input type='password' placeholder='仅本次提交' {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name='temperature'
          render={({ field }) => (
            <FormItem>
              <FormLabel>Temperature</FormLabel>
              <FormControl>
                <Input
                  type='number'
                  min='0'
                  max='2'
                  step='0.1'
                  {...field}
                  value={field.value as string | number | undefined}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name='capabilities_enabled'
          render={({ field }) => (
            <FormItem className='flex items-center justify-between rounded-md border p-3'>
              <div className='space-y-1'>
                <FormLabel>附件能力矩阵（可选）</FormLabel>
                <p className='text-sm text-muted-foreground'>
                  关闭时按模型名自动探测（如 qwen-vl 识别为视觉）
                </p>
              </div>
              <FormControl>
                <Switch
                  checked={!!field.value}
                  onCheckedChange={field.onChange}
                  aria-label='显式配置附件能力矩阵'
                />
              </FormControl>
            </FormItem>
          )}
        />
        {capabilitiesEnabled && (
          <div className='space-y-3 rounded-md border p-3'>
            {CAPABILITY_FIELDS.map((item) => (
              <FormField
                key={item.key}
                control={form.control}
                name={`capabilities.${item.key}`}
                render={({ field }) => (
                  <FormItem className='flex items-start gap-2 space-y-0'>
                    <FormControl>
                      <Checkbox
                        checked={!!field.value}
                        onCheckedChange={(checked) =>
                          field.onChange(checked === true)
                        }
                        className='mt-0.5'
                      />
                    </FormControl>
                    <div className='space-y-0.5'>
                      <FormLabel className='font-normal'>
                        {item.label}
                      </FormLabel>
                      <p className='text-xs text-muted-foreground'>
                        {item.hint}
                      </p>
                    </div>
                  </FormItem>
                )}
              />
            ))}
          </div>
        )}
        <FormField
          control={form.control}
          name='system_prompt'
          render={({ field }) => (
            <FormItem>
              <FormLabel>系统提示词</FormLabel>
              <FormControl>
                <Textarea rows={6} {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <div className='flex justify-end'>
          <Button
            type='submit'
            form='agent-version-form'
            disabled={mutation.isPending}
          >
            {mutation.isPending ? '保存中...' : '创建版本'}
          </Button>
        </div>
      </form>
    </Form>
  )
}
