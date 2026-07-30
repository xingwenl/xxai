import { http } from '@/lib/http'

export type ChatAttachment = {
  id: string
  fileId?: number
  filename: string
  originalName: string
  mimetype: string
  size: number
  url: string
  downloadUrl: string
  storagePath?: string
  description?: string
  kind: 'image' | 'pdf' | 'spreadsheet' | 'text' | 'file'
  extractedText?: string
}

export type MessageCitation = {
  index: number
  sourceType: 'kb_document' | 'kb_text' | 'conversation_attachment'
  title: string
  sourceName: string
  snippet: string
  locator?: Record<string, unknown> | null
  score?: number
}

export type Message = {
  id: number
  conversation_id: number
  sender_id: number
  content: string
  content_type: 'text' | 'image' | 'file'
  attachments?: ChatAttachment[]
  citations?: MessageCitation[]
  create_time: string
  read_by?: string[]
  sender?: {
    id: number
    username: string
    nickname?: string | null
    avatar?: string | null
    is_bot?: number
  } | null
}

export type Conversation = {
  id: number
  type: 'private' | 'group'
  participants: string[]
  owner_id?: number | null
  name?: string | null
  avatar?: string | null
  announcement?: string | null
  participants_users?: Array<{
    id: number
    username: string
    nickname?: string | null
    avatar?: string | null
    is_bot?: number
  }>
  lastMessage?: Message
  unreadCount?: number
}

export type Paginated<T> = {
  items: T[]
  total: number
  page: number
  pageSize: number
  totalPage?: number
}

export type GroupMember = {
  id: number
  conversation_id: number
  user_id: number
  role: 'owner' | 'member'
  invited_by?: number | null
  join_time?: string | null
  user?: {
    id: number
    username: string
    nickname?: string | null
    avatar?: string | null
    is_bot?: number
  } | null
}

export async function ensurePrivateConversation(userId: number) {
  const { data } = await http.post<{ id: number }>(
    '/api/chat/conversation/private',
    {
      userId: String(userId),
    }
  )
  return data
}

export async function createGroupConversation(input: {
  name: string
  memberIds: string[]
  avatar?: string
  announcement?: string
}) {
  const { data } = await http.post<Conversation>('/api/chat/group', input)
  return data
}

export async function getMyConversations(params: {
  page: number
  pageSize: number
  keyword?: string
}): Promise<Paginated<Conversation>> {
  const { data } = await http.get<Paginated<Conversation>>(
    '/api/chat/conversations/my',
    {
      params,
    }
  )
  return data
}

export async function getGroupMembers(conversationId: number) {
  const { data } = await http.get<GroupMember[]>(
    `/api/chat/group/${conversationId}/members`
  )
  return data
}

export async function inviteGroupMembers(
  conversationId: number,
  userIds: string[]
) {
  const { data } = await http.post<Conversation>(
    `/api/chat/group/${conversationId}/invite`,
    { userIds }
  )
  return data
}

export async function getConversationMessages(params: {
  conversationId: number
  page: number
  pageSize: number
}): Promise<Paginated<Message>> {
  const { data } = await http.get<Paginated<Message>>(
    `/api/chat/${params.conversationId}/messages`,
    { params: { page: params.page, pageSize: params.pageSize } }
  )
  return data
}

export async function clearConversationMessages(conversationId: number) {
  const { data } = await http.delete<{
    conversationId: number
    cleared: boolean
    affected: number
  }>(`/api/chat/${conversationId}/messages`)
  return data
}

export async function hideConversation(conversationId: number) {
  const { data } = await http.delete<{
    conversationId: number
    hidden: boolean
    hiddenAt: string
  }>(`/api/chat/${conversationId}`)
  return data
}

export async function uploadChatFiles(
  files: File[]
): Promise<ChatAttachment[]> {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  const { data } = await http.post<{ items: ChatAttachment[] }>(
    '/api/upload/files',
    form,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60_000,
    }
  )
  return data.items
}
