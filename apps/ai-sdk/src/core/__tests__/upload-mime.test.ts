import { describe, it, expect } from 'vitest'
import {
  DEFAULT_UPLOAD_MIME,
  MIME_BY_EXTENSION,
  UPLOAD_ACCEPT,
  extensionOf,
  resolveFileMimeType,
  withResolvedMimeType,
} from '../upload-mime'

const XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

describe('extensionOf', () => {
  it('取小写扩展名', () => {
    expect(extensionOf('Report.XLSX')).toBe('xlsx')
    expect(extensionOf('a.b.csv')).toBe('csv')
  })

  it('无扩展名或以点结尾时返回空串', () => {
    expect(extensionOf('README')).toBe('')
    expect(extensionOf('trailing.')).toBe('')
    expect(extensionOf('.gitignore')).toBe('')
  })
})

describe('MIME_BY_EXTENSION', () => {
  it('覆盖后端允许的文档与图片类型', () => {
    expect(MIME_BY_EXTENSION.xlsx).toBe(XLSX_MIME)
    expect(MIME_BY_EXTENSION.docx).toBe(
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )
    expect(MIME_BY_EXTENSION.pptx).toBe(
      'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    )
    expect(MIME_BY_EXTENSION.pdf).toBe('application/pdf')
    expect(MIME_BY_EXTENSION.csv).toBe('text/csv')
    expect(MIME_BY_EXTENSION.md).toBe('text/markdown')
    expect(MIME_BY_EXTENSION.txt).toBe('text/plain')
    expect(MIME_BY_EXTENSION.jpg).toBe('image/jpeg')
  })
})

describe('resolveFileMimeType', () => {
  it('浏览器已给出类型时不覆盖', () => {
    expect(resolveFileMimeType({ name: 'a.bin', type: 'image/png' })).toBe('image/png')
  })

  it('类型为空时按扩展名推断（大小写无关）', () => {
    expect(resolveFileMimeType({ name: '2026-10 账单.XLSX', type: '' })).toBe(XLSX_MIME)
    expect(resolveFileMimeType({ name: 'notes.md', type: '' })).toBe('text/markdown')
    expect(resolveFileMimeType({ name: 'data.csv' })).toBe('text/csv')
  })

  it('认不出扩展名时回退到 octet-stream', () => {
    expect(resolveFileMimeType({ name: 'archive.zip', type: '' })).toBe(DEFAULT_UPLOAD_MIME)
    expect(resolveFileMimeType({ name: 'noext', type: '' })).toBe(DEFAULT_UPLOAD_MIME)
  })
})

describe('withResolvedMimeType', () => {
  it('类型为空时重建带 type 的 File', () => {
    const raw = new File(['a,b'], '账单.xlsx', { type: '' })
    const normalized = withResolvedMimeType(raw)
    expect(normalized).not.toBe(raw)
    expect(normalized.type).toBe(XLSX_MIME)
    expect(normalized.name).toBe('账单.xlsx')
  })

  it('类型已存在时原样返回同一个 File', () => {
    const raw = new File(['x'], 'a.png', { type: 'image/png' })
    expect(withResolvedMimeType(raw)).toBe(raw)
  })

  it('扩展名未知时不做无意义重建', () => {
    const raw = new File(['x'], 'a.zip', { type: '' })
    expect(withResolvedMimeType(raw)).toBe(raw)
  })
})

describe('UPLOAD_ACCEPT', () => {
  it('只包含 MIME，不含扩展名 token（桌面端会丢弃扩展名）', () => {
    const tokens = UPLOAD_ACCEPT.split(',')
    expect(tokens).toContain(XLSX_MIME)
    expect(tokens).toContain('application/pdf')
    expect(tokens.every((token) => token.includes('/'))).toBe(true)
    expect(tokens.some((token) => token.startsWith('.'))).toBe(false)
  })
})
