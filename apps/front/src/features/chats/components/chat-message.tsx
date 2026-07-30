import { memo } from 'react'
import { Download, ExternalLink, FileText } from 'lucide-react'
import { type Message, type MessageCitation } from '@/api/chat'
import { getApiUrl, getImageUrl } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { MarkdownMessage } from './markdown-message'

type ChatMessageProps = {
  message: Message
  mine: boolean
  aiUserId?: number | null
  showSender?: boolean
}

export const ChatMessage = memo(function ChatMessage({
  message,
  mine,
  aiUserId,
  showSender = false,
}: ChatMessageProps) {
  const time = new Date(message.create_time).toLocaleTimeString()
  const isAi =
    typeof aiUserId === 'number' &&
    Number(message.sender_id) === Number(aiUserId)
  const isStreaming = Number(message.id) < 0
  const senderName =
    message.sender?.nickname ||
    message.sender?.username ||
    `用户 ${message.sender_id}`
  const attachments = Array.isArray(message.attachments)
    ? message.attachments
    : []
  const citations = Array.isArray(message.citations) ? message.citations : []
  const htmlPages = isAi ? extractHtmlPages(message.content) : []

  if (
    message.content_type === 'image' ||
    attachments.some((a) => a.kind === 'image')
  ) {
    const imageUrl =
      attachments.find((a) => a.kind === 'image')?.url || message.content
    return (
      <div
        className={
          mine
            ? 'flex w-full min-w-0 justify-end'
            : 'flex w-full min-w-0 justify-start'
        }
      >
        <div
          className={
            mine
              ? 'w-fit max-w-[88%] min-w-0 rounded-2xl rounded-br-sm bg-primary px-3 py-2 text-primary-foreground sm:max-w-[70%]'
              : 'w-fit max-w-[88%] min-w-0 rounded-2xl rounded-bl-sm bg-muted px-3 py-2 sm:max-w-[70%]'
          }
        >
          {showSender && !mine && (
            <div className='mb-2 text-xs font-medium opacity-70'>
              {senderName}
            </div>
          )}
          <a href={getImageUrl(imageUrl)} target='_blank' rel='noreferrer'>
            <img
              src={getImageUrl(imageUrl)}
              alt='image'
              className='max-h-80 w-auto max-w-full rounded-md object-contain'
              loading='lazy'
            />
          </a>
          <div className='mt-1 text-end text-[10px] opacity-70'>{time}</div>
        </div>
      </div>
    )
  }

  if (message.content_type === 'file') {
    return (
      <div
        className={
          mine
            ? 'flex w-full min-w-0 justify-end'
            : 'flex w-full min-w-0 justify-start'
        }
      >
        <div
          className={
            mine
              ? 'w-fit max-w-[88%] min-w-0 rounded-2xl rounded-br-sm bg-primary px-3 py-2 text-primary-foreground sm:max-w-[70%]'
              : 'w-fit max-w-[88%] min-w-0 rounded-2xl rounded-bl-sm bg-muted px-3 py-2 sm:max-w-[70%]'
          }
        >
          {showSender && !mine && (
            <div className='mb-2 text-xs font-medium opacity-70'>
              {senderName}
            </div>
          )}
          {message.content && !message.content.startsWith('[文件]') && (
            <div className='mb-2 text-sm break-words whitespace-pre-wrap'>
              {message.content}
            </div>
          )}
          <div className='grid gap-2'>
            {attachments.length > 0 ? (
              attachments.map((item) => (
                <a
                  key={item.id || item.filename}
                  href={getImageUrl(item.downloadUrl || item.url)}
                  target='_blank'
                  rel='noreferrer'
                  className={
                    mine
                      ? 'flex min-w-0 items-center gap-3 rounded-xl bg-primary-foreground/10 p-3 text-primary-foreground transition hover:bg-primary-foreground/15'
                      : 'flex min-w-0 items-center gap-3 rounded-xl bg-background p-3 transition hover:bg-background/80'
                  }
                >
                  <span
                    className={
                      mine
                        ? 'flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary-foreground/15'
                        : 'flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted'
                    }
                  >
                    <FileText className='size-4' />
                  </span>
                  <span className='min-w-0 flex-1'>
                    <span className='block truncate text-sm font-medium'>
                      {item.originalName || item.filename}
                    </span>
                    <span className='block truncate text-xs opacity-70'>
                      {formatFileSize(item.size)} · {formatFileKind(item.kind)}
                    </span>
                  </span>
                  <Download className='size-4 shrink-0 opacity-70' />
                </a>
              ))
            ) : (
              <div className='text-sm'>{message.content}</div>
            )}
          </div>
          <div className='mt-1 text-end text-[10px] opacity-70'>{time}</div>
        </div>
      </div>
    )
  }

  return (
    <div
      className={
        mine
          ? 'flex w-full min-w-0 justify-end'
          : 'flex w-full min-w-0 justify-start'
      }
    >
      <div
        className={
          mine
            ? 'w-fit max-w-[88%] min-w-0 rounded-2xl rounded-br-sm bg-primary px-3 py-2 text-sm text-primary-foreground sm:max-w-[70%]'
            : 'w-fit max-w-[88%] min-w-0 rounded-2xl rounded-bl-sm bg-muted px-3 py-2 text-sm sm:max-w-[70%]'
        }
      >
        {showSender && !mine && (
          <div className='mb-2 text-xs font-medium opacity-70'>
            {senderName}
          </div>
        )}
        {htmlPages.length > 0 && (
          <div className='mb-3 grid gap-2'>
            {htmlPages.map((page) => (
              <a
                key={page.href}
                href={getApiUrl(page.href)}
                target='_blank'
                rel='noreferrer noopener'
                className='group flex items-center justify-between gap-3 rounded-xl border border-border/60 bg-background/70 px-3 py-2 text-foreground transition hover:border-primary/40 hover:bg-background'
              >
                <div className='min-w-0'>
                  <div className='text-xs text-muted-foreground'>HTML 页面</div>
                  <div className='truncate text-sm font-medium'>
                    {page.title || page.href}
                  </div>
                </div>
                <ExternalLink className='size-4 shrink-0 opacity-70 transition group-hover:opacity-100' />
              </a>
            ))}
          </div>
        )}
        {isAi ? (
          <MarkdownMessage
            content={injectHtmlPageAnchors(
              injectCitationAnchors(message.content, citations)
            )}
            streaming={isStreaming}
            renderLink={({ href, children }) => {
              const citation = getCitationFromHref(href, citations)
              if (!citation) {
                return renderDefaultLink(href, children)
              }
              return (
                <CitationPopover
                  citation={citation}
                  label={`[${citation.index}]`}
                />
              )
            }}
          />
        ) : (
          <div className='break-words whitespace-pre-wrap'>
            {message.content}
          </div>
        )}
        <div className='mt-1 text-end text-[10px] opacity-70'>{time}</div>
      </div>
    </div>
  )
})

function injectCitationAnchors(content: string, citations: MessageCitation[]) {
  if (!citations.length) return content
  const indexes = new Set(citations.map((item) => Number(item.index)))
  return String(content || '').replace(/\[(\d+)\]/g, (match, rawIndex) => {
    const index = Number(rawIndex)
    if (!indexes.has(index)) return match
    return `[引用${index}](#citation-${index})`
  })
}

function getCitationFromHref(
  href: string | undefined,
  citations: MessageCitation[]
) {
  if (!href) return null
  const match = href.match(/^#citation-(\d+)$/)
  if (!match) return null
  const index = Number(match[1])
  return citations.find((item) => Number(item.index) === index) ?? null
}

function renderDefaultLink(
  href: string | undefined,
  children: React.ReactNode
) {
  const safeHref =
    typeof href === 'string'
      ? unwrapMarkdownHref(String(href || '').trim())
      : ''
  if (!safeHref) return <span>{children}</span>
  const normalized = safeHref.trim().toLowerCase()
  const safe =
    normalized.startsWith('http://') ||
    normalized.startsWith('https://') ||
    normalized.startsWith('mailto:') ||
    normalized.startsWith('/') ||
    normalized.startsWith('#')
  if (!safe) return <span>{children}</span>
  const external =
    normalized.startsWith('http://') || normalized.startsWith('https://')
  const resolvedHref = normalized.startsWith('/')
    ? getApiUrl(safeHref)
    : safeHref
  return (
    <a
      href={resolvedHref}
      target={external || normalized.startsWith('/') ? '_blank' : undefined}
      rel={
        external || normalized.startsWith('/')
          ? 'noreferrer noopener'
          : undefined
      }
      className='underline underline-offset-2'
    >
      {children}
    </a>
  )
}

type HtmlPageLink = {
  title: string
  href: string
}

function injectHtmlPageAnchors(content: string) {
  return String(content || '').replace(
    /(^|[\s>（(])((\/pages\/chat\/[a-z0-9-]+))(?!\]\()(?!(?:[)\]/\w-]))/gim,
    (_match, prefix: string, href: string) => `${prefix}[${href}](${href})`
  )
}

function extractHtmlPages(content: string): HtmlPageLink[] {
  const source = String(content || '')
  const links = new Map<string, HtmlPageLink>()
  const markdownLinkPattern =
    /\[([^\]]+)\]\(((?:https?:\/\/[^\s)]+)?\/pages\/chat\/[a-z0-9-]+)\)/gim
  const rawLinkPattern = /(?:https?:\/\/[^\s)]+)?\/pages\/chat\/[a-z0-9-]+/gim

  for (const match of source.matchAll(markdownLinkPattern)) {
    const title = String(match[1] || '').trim()
    const href = normalizeHtmlPageHref(String(match[2] || '').trim())
    if (!href) continue
    links.set(href, {
      href,
      title:
        title && title !== href ? title : deriveHtmlPageTitleFromHref(href),
    })
  }

  for (const match of source.matchAll(rawLinkPattern)) {
    const href = normalizeHtmlPageHref(String(match[0] || '').trim())
    if (!href || links.has(href)) continue
    links.set(href, {
      href,
      title: deriveHtmlPageTitleFromHref(href),
    })
  }

  return Array.from(links.values())
}

function deriveHtmlPageTitleFromHref(href: string) {
  const slug = href.split('/').filter(Boolean).pop() || href
  return slug
    .split('-')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function normalizeHtmlPageHref(href: string) {
  const safeHref = unwrapMarkdownHref(String(href || '').trim())
  if (!safeHref) return ''
  if (safeHref.startsWith('/pages/chat/')) return safeHref
  try {
    const url = new URL(safeHref)
    return /^\/pages\/chat\/[a-z0-9-]+$/i.test(url.pathname) ? url.pathname : ''
  } catch {
    return ''
  }
}

function unwrapMarkdownHref(value: string) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const match = raw.match(/^\[([^\]]+)\]\((.+)\)$/)
  if (!match) return raw
  return String(match[2] || '').trim()
}

function CitationPopover({
  citation,
  label,
}: {
  citation: MessageCitation
  label: string
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type='button'
          className='mx-0.5 inline-flex cursor-pointer items-center rounded-sm px-1 align-baseline text-xs font-semibold text-foreground underline decoration-dotted underline-offset-2 transition hover:bg-foreground/10'
        >
          {label}
        </button>
      </PopoverTrigger>
      <PopoverContent align='start' className='w-80 space-y-3 p-3'>
        <div className='flex items-start justify-between gap-3'>
          <div className='space-y-1'>
            <div className='text-sm leading-tight font-semibold'>
              [{citation.index}] {citation.title || citation.sourceName}
            </div>
            <div className='text-xs text-muted-foreground'>
              {citation.sourceName}
            </div>
          </div>
          <Badge variant='outline'>
            {formatCitationSourceType(citation.sourceType)}
          </Badge>
        </div>
        <div className='rounded-md bg-muted/60 p-3 text-xs leading-5 text-foreground/90'>
          {citation.snippet}
        </div>
      </PopoverContent>
    </Popover>
  )
}

function formatCitationSourceType(sourceType: MessageCitation['sourceType']) {
  if (sourceType === 'kb_document') return '知识库文档'
  if (sourceType === 'kb_text') return '手工知识'
  return '会话附件'
}

function formatFileKind(kind?: string) {
  if (kind === 'spreadsheet') return '表格'
  if (kind === 'pdf') return 'PDF'
  if (kind === 'text') return '文本'
  if (kind === 'image') return '图片'
  return '文件'
}

function formatFileSize(size: number) {
  if (!Number.isFinite(size) || size <= 0) return '未知大小'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}
