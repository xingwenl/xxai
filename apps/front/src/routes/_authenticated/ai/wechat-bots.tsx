import { createFileRoute } from '@tanstack/react-router'
import { WeChatBotsPage } from '@/features/wechat-bots'

export const Route = createFileRoute('/_authenticated/ai/wechat-bots')({
  component: WeChatBotsPage,
})
