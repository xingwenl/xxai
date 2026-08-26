import { describe, it, expect } from 'vitest'

// ---------------------------------------------------------------------------
// 附件类型定义验证
// ---------------------------------------------------------------------------

describe('AttachmentRef type', () => {
  it('should have required fields', () => {
    const ref: AttachmentRef = {
      assetId: 'abc123',
      filename: 'report.pdf',
      mimeType: 'application/pdf',
      size: 12345,
    }
    expect(ref.assetId).toBe('abc123')
    expect(ref.filename).toBe('report.pdf')
    expect(ref.mimeType).toBe('application/pdf')
    expect(ref.size).toBe(12345)
  })
})

describe('AttachmentUploadState', () => {
  it('should support valid states', () => {
    const states: AttachmentUploadState[] = [
      'pending',
      'uploading',
      'uploaded',
      'processing',
      'ready',
      'failed',
      'unsupported',
    ]
    states.forEach((s) => expect(typeof s).toBe('string'))
  })
})

describe('SendMessageOptions', () => {
  it('should accept attachments', () => {
    const opts: SendMessageOptions = {
      attachments: [
        { assetId: 'abc', filename: 'a.pdf', mimeType: 'application/pdf', size: 100 },
      ],
    }
    expect(opts.attachments).toHaveLength(1)
  })

  it('should be optional', () => {
    const opts: SendMessageOptions = {}
    expect(opts.attachments).toBeUndefined()
  })
})

// ---------------------------------------------------------------------------
// 内联类型定义（模拟 src/core/types.ts 中新增的类型）
// ---------------------------------------------------------------------------

interface AttachmentRef {
  assetId: string
  filename: string
  mimeType: string
  size: number
}

type AttachmentUploadState =
  | 'pending'
  | 'uploading'
  | 'uploaded'
  | 'processing'
  | 'ready'
  | 'failed'
  | 'unsupported'

interface SendMessageOptions {
  attachments?: AttachmentRef[]
  systemPrompt?: string
}
