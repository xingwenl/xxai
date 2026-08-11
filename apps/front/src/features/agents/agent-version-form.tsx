import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { createAgentVersion, type AgentVersionInput } from '@/api/agent'
import { Button } from '@/components/ui/button'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

export const versionSchema = z.object({
  system_prompt: z.string().min(1, '请输入系统提示词'),
  model_name: z.string().min(1, '请输入模型名称').max(120),
  model_base_url: z.string().url('请输入有效 URL').optional().or(z.literal('')),
  api_key: z.string().optional(),
  temperature: z.coerce.number().min(0).max(2),
})

type VersionFormInput = z.input<typeof versionSchema>
type VersionForm = z.output<typeof versionSchema>

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
    },
  })
  const mutation = useMutation({
    mutationFn: (values: VersionForm) => {
      const input: AgentVersionInput = {
        ...values,
        api_key: values.api_key || undefined,
        model_base_url: values.model_base_url || undefined,
        model_options: {},
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
