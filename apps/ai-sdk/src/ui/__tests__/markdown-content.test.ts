import MarkdownIt from 'markdown-it'
import { describe, expect, it } from 'vitest'

describe('MarkdownContent rendering pipeline', () => {
  it('renders markdown syntax and strips unsafe HTML', () => {
    const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true })
    const html = markdown.render('# 标题\n\n**重点**\n\n<script>alert(1)</script>')

    expect(html).toContain('<h1>标题</h1>')
    expect(html).toContain('<strong>重点</strong>')
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
  })
})
