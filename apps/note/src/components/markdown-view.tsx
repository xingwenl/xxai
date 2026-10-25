/**
 * Markdown 渲染组件：用 react-markdown（+ remark-gfm）把正文渲染成 React 元素。
 *
 * 选它而不是 markdown-it/marked 的理由：react-markdown 直接产出 React 元素，
 * 不经过 `dangerouslySetInnerHTML`，因此不需要再引 DOMPurify 做净化；链接协议由
 * 它的 urlTransform 默认逻辑过滤，活动内容（script/iframe）用 skipHtml 关掉。
 * 仓库里 `apps/front` 已经在用同一套依赖（v10 / v4），这里复用同一版本，不新增生态。
 */
import Markdown from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ASSET_PREFIX } from '../lib/image-asset'

/** 插件数组放到组件外，避免每次渲染都创建新数组导致整棵 Markdown 重解析。 */
const REMARK_PLUGINS = [remarkGfm]

const COMPONENTS: Components = {
  // 正文里的链接一律交给系统浏览器打开，且不把 iframe 的 window.opener 传出去
  a({ href, children }) {
    return (
      <a href={href} target="_blank" rel="noreferrer noopener">
        {children}
      </a>
    )
  },
  // 只渲染宿主内的本站资产图片；其余一律降级为占位文字：
  // 离线/内网下远程图只会是空白格子，还会把阅读记录发给图床。
  img({ src, alt }) {
    const source = typeof src === 'string' ? src : ''
    if (source.startsWith(ASSET_PREFIX)) {
      return (
        <img
          className="md-img"
          src={source}
          alt={alt?.trim() || '图片'}
          loading="lazy"
          decoding="async"
        />
      )
    }
    const label = alt?.trim() || '未命名'
    return (
      <span className="md-image" role="img" aria-label={`图片：${label}`}>
        图片：{label}
      </span>
    )
  },
}

export function MarkdownView({
  content,
  className,
  emptyText = '这篇笔记还没有正文，点右上角「编辑」或按 ⌘E 开始书写。',
}: {
  content: string
  className?: string
  emptyText?: string
}) {
  const classes = className ? `markdown-view ${className}` : 'markdown-view'

  if (!content.trim()) {
    return (
      <div className={classes}>
        <p className="md-empty">{emptyText}</p>
      </div>
    )
  }

  return (
    <div className={classes}>
      <Markdown remarkPlugins={REMARK_PLUGINS} components={COMPONENTS} skipHtml>
        {content}
      </Markdown>
    </div>
  )
}
