import DOMPurify from 'dompurify'
import 'github-markdown-css/github-markdown.css'
import { type ReactNode } from 'react'
// / 1. 引入一个代码高亮主题，这是解决 CSS 不全的关键
// import 'prismjs/themes/prism-tomorrow.css'
import ReactMarkdown from 'react-markdown'
import rehypePrismPlus from 'rehype-prism-plus'
import remarkGfm from 'remark-gfm'

function isSafeHref(href: string) {
  const v = href.trim().toLowerCase()
  if (
    v.startsWith('http://') ||
    v.startsWith('https://') ||
    v.startsWith('mailto:')
  ) {
    return true
  }
  return v.startsWith('/') || v.startsWith('#')
}

function normalizeForStreaming(source: string, streaming: boolean) {
  if (!streaming) return source
  const fences = source.match(/```/g)?.length ?? 0
  if (fences % 2 === 1) return source + '\n```'
  return source
}

export type MarkdownLinkRendererProps = {
  href?: string
  children: ReactNode
}

export function MarkdownMessage({
  content,
  streaming = false,
  renderLink,
}: {
  content: string
  streaming?: boolean
  renderLink?: (props: MarkdownLinkRendererProps) => ReactNode
}) {
  const safe = DOMPurify.sanitize(String(content || ''), {
    ALLOWED_TAGS: [],
    ALLOWED_ATTR: [],
  })
  const source = normalizeForStreaming(safe, streaming)

  return (
    <div
      className='markdown markdown-body inline-block min-w-0 max-w-full overflow-hidden break-words align-top [&_pre]:max-w-full [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:p-3 [&_pre]:text-xs [&_pre_code]:whitespace-pre [&_pre_code]:break-normal [&_code]:break-words'
      style={{
        backgroundColor: 'transparent',
        margin: 0,
        maxWidth: '100%',
        minWidth: 0,
        padding: 0,
      }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypePrismPlus]}
        components={{
          a: ({ href, children }) => {
            if (renderLink) {
              return <>{renderLink({ href, children })}</>
            }
            const safeHref = typeof href === 'string' ? href : ''
            if (!safeHref || !isSafeHref(safeHref)) return <span>{children}</span>
            const external =
              safeHref.startsWith('http://') || safeHref.startsWith('https://')
            return (
              <a
                href={safeHref}
                target={external ? '_blank' : undefined}
                rel={external ? 'noreferrer noopener' : undefined}
                className='underline underline-offset-2'
              >
                {children}
              </a>
            )
          },
          pre: ({ children }) => (
            <pre className='max-w-full overflow-x-auto whitespace-pre rounded-md p-3 text-xs'>
              {children}
            </pre>
          ),
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  )
}
