import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Plus, Settings2, Trash2, Users } from 'lucide-react'
import { toast } from 'sonner'
import {
  clearConversationMessages,
  createGroupConversation,
  ensurePrivateConversation,
  getGroupMembers,
  getConversationMessages,
  getMyConversations,
  hideConversation,
  inviteGroupMembers,
  type Message,
  type Paginated,
} from '@/api/chat'
import {
  applyFriend,
  getFriendList,
  getFriendRequests,
  handleFriend,
  removeFriend,
} from '@/api/friend'
import { useAuthStore } from '@/stores/auth-store'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { ChatComposer } from './components/chat-composer'
import { ChatMessageList } from './components/chat-message-list'
import { useChatRoom } from './hooks/use-chat-room'
import { useChatSendMessage } from './hooks/use-chat-send-message'
import { useChatSocketConnection } from './hooks/use-chat-socket-connection'
import { useChatSocketEvents } from './hooks/use-chat-socket-events'

type TabKey = 'conversations' | 'friends' | 'requests'

type DisplayUser = {
  alias?: string | null
  nickname?: string | null
  username?: string | null
}

function isTabKey(v: string): v is TabKey {
  return v === 'conversations' || v === 'friends' || v === 'requests'
}

function displayName(u?: DisplayUser | null) {
  return u?.alias || u?.nickname || u?.username || 'Unknown'
}

function formatLastMessage(message?: Message) {
  if (!message) return ''
  if (message.content_type === 'file') {
    const first = message.attachments?.[0]
    return `[文件] ${first?.originalName || message.content.replace(/^\[文件\]\s*/, '') || '附件'}`
  }
  if (message.content_type === 'image') return '[图片]'
  return message.content || ''
}

type TabLabelWithBadgeProps = {
  label: string
  count?: number
}

function TabLabelWithBadge({ label, count = 0 }: TabLabelWithBadgeProps) {
  return (
    <span className='relative inline-flex items-center pe-3'>
      <span>{label}</span>
      {count > 0 && (
        <span className='absolute -top-2 -right-2 rounded-full bg-primary px-1.5 py-0.5 text-[10px] leading-none text-primary-foreground'>
          {count}
        </span>
      )}
    </span>
  )
}

export function Chats() {
  const qc = useQueryClient()
  const { auth } = useAuthStore()
  const currentUserId = auth.user?.id
  const token = auth.accessToken

  const [tab, setTab] = useState<TabKey>('conversations')
  const [selectedConversationId, setSelectedConversationId] = useState<
    number | null
  >(null)
  const [addOpen, setAddOpen] = useState(false)
  const [createGroupOpen, setCreateGroupOpen] = useState(false)
  const [groupSettingsOpen, setGroupSettingsOpen] = useState(false)
  const [clearOpen, setClearOpen] = useState(false)
  const [hideOpen, setHideOpen] = useState(false)
  const [addFriendId, setAddFriendId] = useState('')
  const [addAlias, setAddAlias] = useState('')
  const [groupName, setGroupName] = useState('')
  const [groupMemberIds, setGroupMemberIds] = useState<string[]>([])
  const [inviteMemberIds, setInviteMemberIds] = useState<string[]>([])

  const conversationsQuery = useQuery({
    queryKey: ['chat', 'conversations', { page: 1, pageSize: 50 }],
    queryFn: () => getMyConversations({ page: 1, pageSize: 50 }),
  })

  const friendsQuery = useQuery({
    queryKey: ['friend', 'list'],
    queryFn: getFriendList,
  })

  const requestsQuery = useQuery({
    queryKey: ['friend', 'requests'],
    queryFn: getFriendRequests,
  })

  const messagesQuery = useQuery({
    queryKey: [
      'chat',
      'messages',
      { id: selectedConversationId, page: 1, pageSize: 50 },
    ],
    queryFn: () =>
      getConversationMessages({
        conversationId: selectedConversationId as number,
        page: 1,
        pageSize: 50,
      }),
    enabled: !!selectedConversationId,
  })

  const ensureMutation = useMutation({
    mutationFn: (userId: number) => ensurePrivateConversation(userId),
    onSuccess: async (res) => {
      setSelectedConversationId(Number(res.id))
      setTab('conversations')
      await qc.invalidateQueries({ queryKey: ['chat', 'conversations'] })
    },
  })

  const applyMutation = useMutation({
    mutationFn: (p: { friendId: number; alias?: string }) => applyFriend(p),
    onSuccess: async () => {
      toast.success('已添加好友')
      setAddOpen(false)
      setAddFriendId('')
      setAddAlias('')
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['friend', 'requests'] }),
        qc.invalidateQueries({ queryKey: ['friend', 'list'] }),
      ])
    },
  })

  const handleMutation = useMutation({
    mutationFn: (p: { friendId: number; status: 1 | 2 }) => handleFriend(p),
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['friend', 'requests'] }),
        qc.invalidateQueries({ queryKey: ['friend', 'list'] }),
      ])
    },
  })

  const removeMutation = useMutation({
    mutationFn: (friendId: number) => removeFriend(friendId),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['friend', 'list'] })
    },
  })

  const clearMessagesMutation = useMutation({
    mutationFn: (conversationId: number) =>
      clearConversationMessages(conversationId),
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['chat', 'conversations'] }),
        qc.invalidateQueries({ queryKey: ['chat', 'messages'] }),
      ])
      setClearOpen(false)
      toast.success('Chat cleared')
    },
  })

  const hideConversationMutation = useMutation({
    mutationFn: (conversationId: number) => hideConversation(conversationId),
    onSuccess: async (_, conversationId) => {
      await qc.invalidateQueries({ queryKey: ['chat', 'conversations'] })
      qc.removeQueries({
        queryKey: ['chat', 'messages', { id: conversationId, page: 1, pageSize: 50 }],
      })
      if (Number(selectedConversationId) === Number(conversationId)) {
        setSelectedConversationId(null)
      }
      setHideOpen(false)
      toast.success('已从会话列表移除')
    },
  })

  const createGroupMutation = useMutation({
    mutationFn: () =>
      createGroupConversation({
        name: groupName.trim(),
        memberIds: groupMemberIds,
      }),
    onSuccess: async (conversation) => {
      await qc.invalidateQueries({ queryKey: ['chat', 'conversations'] })
      setCreateGroupOpen(false)
      setGroupName('')
      setGroupMemberIds([])
      setSelectedConversationId(Number(conversation.id))
      setTab('conversations')
      toast.success('群组创建成功')
    },
  })

  const inviteMembersMutation = useMutation({
    mutationFn: () =>
      inviteGroupMembers(selectedConversationId as number, inviteMemberIds),
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['chat', 'conversations'] }),
        qc.invalidateQueries({
          queryKey: ['chat', 'group-members', selectedConversationId],
        }),
      ])
      setInviteMemberIds([])
      toast.success('已邀请成员入群')
    },
  })

  const list = useMemo(
    () =>
      Array.isArray(conversationsQuery.data?.items)
        ? conversationsQuery.data.items
        : [],
    [conversationsQuery.data]
  )
  const friends = useMemo(
    () => (Array.isArray(friendsQuery.data) ? friendsQuery.data : []),
    [friendsQuery.data]
  )
  const friendRequests = useMemo(
    () => (Array.isArray(requestsQuery.data) ? requestsQuery.data : []),
    [requestsQuery.data]
  )
  const chatUnreadCount = list.reduce(
    (sum, item) => sum + Number(item.unreadCount || 0),
    0
  )
  const requestCount = friendRequests.length
  const selectedConversation = useMemo(() => {
    if (!selectedConversationId) return null
    return (
      list.find((c) => Number(c.id) === Number(selectedConversationId)) ?? null
    )
  }, [list, selectedConversationId])

  const aiUserId = useMemo(() => {
    const users = selectedConversation?.participants_users ?? []
    const ai = users.find((u) => Number(u.is_bot || 0) === 1)
    return ai?.id ?? null
  }, [selectedConversation])

  const groupMembersQuery = useQuery({
    queryKey: ['chat', 'group-members', selectedConversationId],
    queryFn: () => getGroupMembers(selectedConversationId as number),
    enabled:
      Boolean(selectedConversationId) && selectedConversation?.type === 'group',
  })

  const currentUserIsGroupOwner = useMemo(() => {
    if (!selectedConversation || selectedConversation.type !== 'group') {
      return false
    }
    return Number(selectedConversation.owner_id) === Number(currentUserId)
  }, [currentUserId, selectedConversation])

  const availableFriendsForGroup = useMemo(
    () =>
      friends.filter(
        (friend) =>
          !selectedConversation?.participants?.includes(String(friend.id))
      ),
    [friends, selectedConversation]
  )

  const conversationTitle = useMemo(() => {
    if (!selectedConversation) return 'Conversation'
    if (selectedConversation.type === 'group') {
      return selectedConversation.name || '群聊'
    }
    const other =
      selectedConversation.participants_users?.find(
        (p) => p.id !== currentUserId
      ) ?? selectedConversation.participants_users?.[0]
    return displayName(other)
  }, [currentUserId, selectedConversation])

  const toggleMemberSelection = (
    id: string,
    setValue: React.Dispatch<React.SetStateAction<string[]>>
  ) => {
    setValue((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    )
  }

  const onAddFriend = () => {
    const id = Number(addFriendId)
    if (!Number.isFinite(id) || id <= 0) {
      toast.error('Invalid userId')
      return
    }
    applyMutation.mutate({ friendId: id, alias: addAlias || undefined })
  }

  const selectConversation = (conversationId: number) => {
    setSelectedConversationId(conversationId)
    qc.setQueryData<Paginated<(typeof list)[number]>>(
      ['chat', 'conversations', { page: 1, pageSize: 50 }],
      (old) => {
        if (!old) return old
        return {
          ...old,
          items: old.items.map((item) =>
            Number(item.id) === Number(conversationId)
              ? { ...item, unreadCount: 0 }
              : item
          ),
        }
      }
    )
  }

  const { connected: wsConnected } = useChatSocketConnection(token)
  useChatSocketEvents({
    token,
    qc,
    currentUserId,
    selectedConversationId,
  })
  useChatRoom({ token, conversationId: selectedConversationId })
  const sendMessage = useChatSendMessage({
    token,
    conversationId: selectedConversationId,
  })
  const showConversationList = !selectedConversationId
  const showConversationPanel = Boolean(selectedConversationId)

  const handleClearConversation = () => {
    if (!selectedConversationId) return
    clearMessagesMutation.mutate(selectedConversationId)
  }

  const handleHideConversation = () => {
    if (!selectedConversationId) return
    hideConversationMutation.mutate(selectedConversationId)
  }

  return (
    <>
      <Header>
        <Search />
        <div className='ms-auto flex items-center space-x-4'>
          <ThemeSwitch />
          <ConfigDrawer />
          <ProfileDropdown />
        </div>
      </Header>

      <Main fixed fluid>
        <section className='flex h-full min-h-0 min-w-0 gap-6'>
          <div
            className={
              showConversationList
                ? 'flex min-h-0 w-full flex-col gap-2 sm:w-72 2xl:w-80'
                : 'hidden min-h-0 w-full flex-col gap-2 sm:flex sm:w-72 2xl:w-80'
            }
          >
            <div className='flex items-center justify-between'>
              <Tabs
                value={tab}
                onValueChange={(v) => {
                  if (isTabKey(v)) setTab(v)
                }}
              >
                <TabsList>
                  <TabsTrigger value='conversations'>
                    <TabLabelWithBadge label='Chats' count={chatUnreadCount} />
                  </TabsTrigger>
                  <TabsTrigger value='friends'>Friends</TabsTrigger>
                  <TabsTrigger value='requests'>
                    <TabLabelWithBadge label='Requests' count={requestCount} />
                  </TabsTrigger>
                </TabsList>
              </Tabs>
              {tab === 'friends' && (
                <Button
                  size='icon'
                  variant='ghost'
                  onClick={() => setAddOpen(true)}
                >
                  <Plus />
                </Button>
              )}
              {tab === 'conversations' && (
                <Button
                  size='icon'
                  variant='ghost'
                  onClick={() => setCreateGroupOpen(true)}
                >
                  <Users />
                </Button>
              )}
            </div>

            <Tabs
              value={tab}
              onValueChange={(v) => {
                if (isTabKey(v)) setTab(v)
              }}
              className='h-full min-h-0'
            >
              <TabsContent value='conversations' className='h-full min-h-0'>
                <ScrollArea className='h-full'>
                  <div className='flex flex-col gap-1 p-1'>
                    {list.map((c) => {
                      const other =
                        c.participants_users?.find(
                          (p) => p.id !== currentUserId
                        ) ?? c.participants_users?.[0]
                      const name =
                        c.type === 'group'
                          ? c.name || '群聊'
                          : displayName(other)
                      const last = formatLastMessage(c.lastMessage)
                      const unread = Number(c.unreadCount || 0)
                      return (
                        <button
                          key={c.id}
                          type='button'
                          onClick={() => selectConversation(Number(c.id))}
                          className={
                            Number(selectedConversationId) === Number(c.id)
                              ? 'flex items-center gap-3 rounded-md bg-accent px-3 py-2 text-left'
                              : 'flex items-center gap-3 rounded-md px-3 py-2 text-left hover:bg-accent'
                          }
                        >
                          <Avatar className='size-9'>
                            <AvatarImage
                              src={
                                c.type === 'group'
                                  ? (c.avatar ?? '')
                                  : (other?.avatar ?? '')
                              }
                              alt={name}
                            />
                            <AvatarFallback>
                              {String(name || '?')
                                .charAt(0)
                                .toUpperCase()}
                            </AvatarFallback>
                          </Avatar>
                          <div className='min-w-0 flex-1'>
                            <div className='flex items-center justify-between gap-2'>
                              <div className='truncate text-sm font-medium'>
                                {name}
                              </div>
                              {unread > 0 && (
                                <div className='rounded-full bg-primary px-2 py-0.5 text-xs text-primary-foreground'>
                                  {unread}
                                </div>
                              )}
                            </div>
                            <div className='truncate text-xs text-muted-foreground'>
                              {last}
                            </div>
                          </div>
                        </button>
                      )
                    })}
                    {list.length === 0 && (
                      <div className='p-6 text-sm text-muted-foreground'>
                        No conversations
                      </div>
                    )}
                  </div>
                </ScrollArea>
              </TabsContent>

              <TabsContent value='friends' className='h-full min-h-0'>
                <ScrollArea className='h-full'>
                  <div className='flex flex-col gap-1 p-1'>
                    {friends.map((f) => {
                      const name = displayName(f)
                      return (
                        <div
                          key={f.id}
                          className='flex items-center gap-3 rounded-md px-3 py-2 hover:bg-accent'
                        >
                          <Avatar className='size-9'>
                            <AvatarImage src={f.avatar ?? ''} alt={name} />
                            <AvatarFallback>
                              {String(name || '?')
                                .charAt(0)
                                .toUpperCase()}
                            </AvatarFallback>
                          </Avatar>
                          <div className='min-w-0 flex-1'>
                            <div className='truncate text-sm font-medium'>
                              {name}
                            </div>
                            <div className='truncate text-xs text-muted-foreground'>
                              ID: {f.id}
                            </div>
                          </div>
                          <div className='flex items-center gap-2'>
                            <Button
                              size='sm'
                              variant='secondary'
                              onClick={() => ensureMutation.mutate(f.id)}
                            >
                              Chat
                            </Button>
                            <Button
                              size='sm'
                              variant='ghost'
                              onClick={() => removeMutation.mutate(f.id)}
                            >
                              Remove
                            </Button>
                          </div>
                        </div>
                      )
                    })}
                    {friends.length === 0 && (
                      <div className='p-6 text-sm text-muted-foreground'>
                        No friends
                      </div>
                    )}
                  </div>
                </ScrollArea>
              </TabsContent>

              <TabsContent value='requests' className='h-full min-h-0'>
                <ScrollArea className='h-full'>
                  <div className='flex flex-col gap-1 p-1'>
                    {friendRequests.map((r) => {
                      const name = displayName(r)
                      return (
                        <div
                          key={r.requestId}
                          className='flex items-center gap-3 rounded-md px-3 py-2 hover:bg-accent'
                        >
                          <Avatar className='size-9'>
                            <AvatarImage src={r.avatar ?? ''} alt={name} />
                            <AvatarFallback>
                              {String(name || '?')
                                .charAt(0)
                                .toUpperCase()}
                            </AvatarFallback>
                          </Avatar>
                          <div className='min-w-0 flex-1'>
                            <div className='truncate text-sm font-medium'>
                              {name}
                            </div>
                            <div className='truncate text-xs text-muted-foreground'>
                              ID: {r.userId}
                            </div>
                          </div>
                          <div className='flex items-center gap-2'>
                            <Button
                              size='sm'
                              onClick={() =>
                                handleMutation.mutate({
                                  friendId: r.userId,
                                  status: 1,
                                })
                              }
                            >
                              Accept
                            </Button>
                            <Button
                              size='sm'
                              variant='secondary'
                              onClick={() =>
                                handleMutation.mutate({
                                  friendId: r.userId,
                                  status: 2,
                                })
                              }
                            >
                              Reject
                            </Button>
                          </div>
                        </div>
                      )
                    })}
                    {friendRequests.length === 0 && (
                      <div className='p-6 text-sm text-muted-foreground'>
                        No requests
                      </div>
                    )}
                  </div>
                </ScrollArea>
              </TabsContent>
            </Tabs>
          </div>

          <div
            className={
              showConversationPanel
                ? 'flex min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden rounded-md border bg-background'
                : 'hidden min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden rounded-md border bg-background sm:flex'
            }
          >
            <div className='flex items-center justify-between border-b p-3 sm:p-4'>
              <div className='flex min-w-0 items-center gap-2'>
                <Button
                  type='button'
                  size='icon'
                  variant='ghost'
                  className='size-8 sm:hidden'
                  aria-label='Back to conversations'
                  onClick={() => setSelectedConversationId(null)}
                >
                  <ArrowLeft />
                </Button>
                <div className='truncate text-sm font-medium'>
                  {conversationTitle}
                </div>
              </div>
              <div className='flex items-center gap-2'>
                {selectedConversation?.type === 'group' && (
                  <Button
                    type='button'
                    size='sm'
                    variant='outline'
                    onClick={() => setGroupSettingsOpen(true)}
                  >
                    <Settings2 className='mr-2 size-4' />
                    Group
                  </Button>
                )}
                {selectedConversationId && (
                  <Button
                    type='button'
                    size='sm'
                    variant='outline'
                    onClick={() => setHideOpen(true)}
                  >
                    <Trash2 className='mr-2 size-4' />
                    Remove from list
                  </Button>
                )}
                {selectedConversationId && (
                  <Button
                    type='button'
                    size='sm'
                    variant='outline'
                    onClick={() => setClearOpen(true)}
                  >
                    <Trash2 className='mr-2 size-4' />
                    Clear chat
                  </Button>
                )}
              </div>
            </div>

            <div className='flex min-h-0 min-w-0 flex-1 flex-col gap-2 overflow-hidden p-3 sm:p-4'>
              <ChatMessageList
                conversationId={selectedConversationId}
                currentUserId={currentUserId}
                aiUserId={aiUserId}
                messages={messagesQuery.data?.items ?? []}
                showSender={selectedConversation?.type === 'group'}
              />

              <ChatComposer
                disabled={!selectedConversationId || !wsConnected}
                onSend={sendMessage}
                mentionOnlyHint={selectedConversation?.type === 'group'}
              />
            </div>
          </div>
        </section>
      </Main>

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Friend</DialogTitle>
          </DialogHeader>
          <div className='grid gap-3'>
            <Input
              value={addFriendId}
              onChange={(e) => setAddFriendId(e.target.value)}
              placeholder='friend userId'
              inputMode='numeric'
            />
            <Input
              value={addAlias}
              onChange={(e) => setAddAlias(e.target.value)}
              placeholder='alias (optional)'
            />
          </div>
          <DialogFooter>
            <Button variant='secondary' onClick={() => setAddOpen(false)}>
              Cancel
            </Button>
            <Button onClick={onAddFriend} disabled={applyMutation.isPending}>
              Add
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={createGroupOpen} onOpenChange={setCreateGroupOpen}>
        <DialogContent className='sm:max-w-lg'>
          <DialogHeader>
            <DialogTitle>创建群组</DialogTitle>
          </DialogHeader>
          <div className='grid gap-4'>
            <div className='grid gap-2'>
              <Label htmlFor='group-name'>群名称</Label>
              <Input
                id='group-name'
                value={groupName}
                onChange={(e) => setGroupName(e.target.value)}
                placeholder='例如：项目讨论组'
              />
            </div>
            <div className='grid gap-2'>
              <Label>选择好友</Label>
              <ScrollArea className='h-64 rounded-md border'>
                <div className='grid gap-2 p-3'>
                  {friends.map((friend) => {
                    const checked = groupMemberIds.includes(String(friend.id))
                    const name = displayName(friend)
                    return (
                      <label
                        key={friend.id}
                        className='flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 hover:bg-accent'
                      >
                        <Checkbox
                          checked={checked}
                          onCheckedChange={() =>
                            toggleMemberSelection(
                              String(friend.id),
                              setGroupMemberIds
                            )
                          }
                        />
                        <Avatar className='size-8'>
                          <AvatarImage src={friend.avatar ?? ''} alt={name} />
                          <AvatarFallback>
                            {String(name || '?').charAt(0).toUpperCase()}
                          </AvatarFallback>
                        </Avatar>
                        <div className='min-w-0 flex-1'>
                          <div className='truncate text-sm font-medium'>
                            {name}
                          </div>
                          <div className='truncate text-xs text-muted-foreground'>
                            ID: {friend.id}
                          </div>
                        </div>
                      </label>
                    )
                  })}
                  {friends.length === 0 && (
                    <div className='text-sm text-muted-foreground'>
                      还没有可选好友
                    </div>
                  )}
                </div>
              </ScrollArea>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant='secondary'
              onClick={() => setCreateGroupOpen(false)}
            >
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (!groupName.trim()) {
                  toast.error('请填写群名称')
                  return
                }
                if (groupMemberIds.length === 0) {
                  toast.error('请至少选择一位好友')
                  return
                }
                createGroupMutation.mutate()
              }}
              disabled={createGroupMutation.isPending}
            >
              {createGroupMutation.isPending ? 'Creating...' : 'Create Group'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Sheet open={groupSettingsOpen} onOpenChange={setGroupSettingsOpen}>
        <SheetContent className='flex flex-col'>
          <SheetHeader className='text-start'>
            <SheetTitle>{conversationTitle}</SheetTitle>
            <SheetDescription>
              群里只有显式 @机器人 时，机器人才会回复。
            </SheetDescription>
          </SheetHeader>

          <div className='flex-1 space-y-4 overflow-hidden'>
            <div className='grid gap-2'>
              <div className='text-sm font-medium'>成员列表</div>
              <ScrollArea className='h-52 rounded-md border'>
                <div className='grid gap-2 p-3'>
                  {(groupMembersQuery.data ?? []).map((member) => {
                    const name = displayName(member.user ?? undefined)
                    return (
                      <div
                        key={`${member.conversation_id}-${member.user_id}`}
                        className='flex items-center gap-3 rounded-md px-2 py-2'
                      >
                        <Avatar className='size-8'>
                          <AvatarImage
                            src={member.user?.avatar ?? ''}
                            alt={name}
                          />
                          <AvatarFallback>
                            {String(name || '?').charAt(0).toUpperCase()}
                          </AvatarFallback>
                        </Avatar>
                        <div className='min-w-0 flex-1'>
                          <div className='truncate text-sm font-medium'>
                            {name}
                          </div>
                          <div className='text-xs text-muted-foreground'>
                            {member.role === 'owner' ? '管理员' : '成员'}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </ScrollArea>
            </div>

            {currentUserIsGroupOwner && (
              <div className='grid gap-2'>
                <div className='text-sm font-medium'>邀请好友入群</div>
                <ScrollArea className='h-48 rounded-md border'>
                  <div className='grid gap-2 p-3'>
                    {availableFriendsForGroup.map((friend) => {
                      const checked = inviteMemberIds.includes(String(friend.id))
                      const name = displayName(friend)
                      return (
                        <label
                          key={friend.id}
                          className='flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 hover:bg-accent'
                        >
                          <Checkbox
                            checked={checked}
                            onCheckedChange={() =>
                              toggleMemberSelection(
                                String(friend.id),
                                setInviteMemberIds
                              )
                            }
                          />
                          <Avatar className='size-8'>
                            <AvatarImage src={friend.avatar ?? ''} alt={name} />
                            <AvatarFallback>
                              {String(name || '?').charAt(0).toUpperCase()}
                            </AvatarFallback>
                          </Avatar>
                          <div className='min-w-0 flex-1'>
                            <div className='truncate text-sm font-medium'>
                              {name}
                            </div>
                            <div className='truncate text-xs text-muted-foreground'>
                              ID: {friend.id}
                            </div>
                          </div>
                        </label>
                      )
                    })}
                    {availableFriendsForGroup.length === 0 && (
                      <div className='text-sm text-muted-foreground'>
                        没有可继续邀请的好友
                      </div>
                    )}
                  </div>
                </ScrollArea>
              </div>
            )}
          </div>

          <SheetFooter className='gap-2'>
            {currentUserIsGroupOwner && (
              <Button
                onClick={() => {
                  if (inviteMemberIds.length === 0) {
                    toast.error('请先选择要邀请的好友')
                    return
                  }
                  inviteMembersMutation.mutate()
                }}
                disabled={inviteMembersMutation.isPending}
              >
                {inviteMembersMutation.isPending ? 'Inviting...' : 'Invite'}
              </Button>
            )}
            <Button
              variant='secondary'
              onClick={() => setGroupSettingsOpen(false)}
            >
              Close
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>

      <Dialog open={clearOpen} onOpenChange={setClearOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Clear current chat?</DialogTitle>
          </DialogHeader>
          <div className='text-sm text-muted-foreground'>
            This will clear all messages in the current conversation. The
            conversation itself will still be kept.
          </div>
          <DialogFooter>
            <Button
              variant='secondary'
              onClick={() => setClearOpen(false)}
              disabled={clearMessagesMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant='destructive'
              onClick={handleClearConversation}
              disabled={clearMessagesMutation.isPending}
            >
              {clearMessagesMutation.isPending ? 'Clearing...' : 'Clear chat'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={hideOpen} onOpenChange={setHideOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove current conversation from list?</DialogTitle>
          </DialogHeader>
          <div className='text-sm text-muted-foreground'>
            This only removes the conversation from your list. If new messages
            arrive later, it will show up again.
          </div>
          <DialogFooter>
            <Button
              variant='secondary'
              onClick={() => setHideOpen(false)}
              disabled={hideConversationMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant='destructive'
              onClick={handleHideConversation}
              disabled={hideConversationMutation.isPending}
            >
              {hideConversationMutation.isPending
                ? 'Removing...'
                : 'Remove from list'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
