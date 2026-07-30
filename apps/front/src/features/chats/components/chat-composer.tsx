import { useCallback, useRef, useState } from 'react'
import { FileUp, Send, X } from 'lucide-react'
import { toast } from 'sonner'
import { type ChatAttachment, uploadChatFiles } from '@/api/chat'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { SendChatMessageInput } from '../hooks/use-chat-send-message'

export function ChatComposer({
  disabled,
  onSend,
  mentionOnlyHint = false,
}: {
  disabled: boolean
  onSend: (input: SendChatMessageInput) => void
  mentionOnlyHint?: boolean
}) {
  const [value, setValue] = useState('')
  const [attachments, setAttachments] = useState<ChatAttachment[]>([])
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const send = useCallback(() => {
    const content = value.trim()
    if (!content && attachments.length === 0) return
    if (attachments.length > 0) {
      const names = attachments.map((item) => item.originalName).join(', ')
      onSend({
        content: content || `[文件] ${names}`,
        contentType: 'file',
        attachments,
      })
    } else {
      onSend(content)
    }
    setValue('')
    setAttachments([])
  }, [attachments, onSend, value])

  const onPickFiles = useCallback(async (files: FileList | null) => {
    const picked = Array.from(files ?? [])
    if (!picked.length) return
    setUploading(true)
    try {
      const uploaded = await uploadChatFiles(picked)
      setAttachments((prev) => [...prev, ...uploaded])
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }, [])

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((item) => item.id !== id))
  }, [])

  return (
    <div className='flex min-w-0 shrink-0 flex-col gap-2'>
      {mentionOnlyHint && (
        <div className='text-xs text-muted-foreground'>
          群聊中只有输入 `@机器人` 时，机器人才会回复。
        </div>
      )}
      {attachments.length > 0 && (
        <div className='flex flex-wrap gap-2 rounded-md border bg-muted/40 p-2'>
          {attachments.map((item) => (
            <div
              key={item.id}
              className='inline-flex max-w-full items-center gap-2 rounded-full bg-background px-2 py-1 text-xs'
            >
              <span className='max-w-48 truncate'>{item.originalName}</span>
              <button
                type='button'
                className='text-muted-foreground hover:text-foreground'
                onClick={() => removeAttachment(item.id)}
                aria-label={`Remove ${item.originalName}`}
              >
                <X className='size-3' />
              </button>
            </div>
          ))}
        </div>
      )}

      <div className='flex min-w-0 gap-2'>
        <input
          ref={fileInputRef}
          type='file'
          multiple
          className='hidden'
          accept='.png,.jpg,.jpeg,.gif,.webp,.pdf,.csv,.txt,.xls,.xlsx'
          onChange={(e) => void onPickFiles(e.target.files)}
        />
        <Button
          type='button'
          variant='secondary'
          size='icon'
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || uploading}
          aria-label='Upload files'
          className='shrink-0'
        >
          <FileUp />
        </Button>
        <Input
          className='min-w-0 flex-1'
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={
            attachments.length > 0 ? 'Add a note...' : 'Type a message...'
          }
          disabled={disabled || uploading}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              send()
            }
          }}
        />
        <Button
          type='button'
          onClick={send}
          disabled={
            disabled || uploading || (!value.trim() && attachments.length === 0)
          }
          className='shrink-0 px-3 sm:px-4'
        >
          <Send />
        </Button>
      </div>
    </div>
  )
}
