/**
 * 附件 MIME 推断。
 *
 * 两个来源约束：
 * 1. 文件选择器在桌面端（macOS WKWebView）只按 MIME 建过滤器，pywebview 会把
 *    `.xlsx` 这类扩展名 token 直接丢弃，导致文档永远选不到，因此 `accept` 只能写 MIME。
 * 2. 部分系统/浏览器回传的 `File.type` 为空，直接上传会以 application/octet-stream
 *    发给后端，被 MIME 白名单拒掉，因此需要按扩展名兜底。
 *
 * 这里的 MIME 取值与后端 `app/modules/asset_processing/runtime.py` 的
 * ALLOWED_MIME_TYPES 保持一致，新增类型时两边要一起改。
 */

/** 默认上传 MIME（浏览器拿不到类型且扩展名未知时使用） */
export const DEFAULT_UPLOAD_MIME = 'application/octet-stream'

/** 扩展名 → MIME。键为小写、不含点。 */
export const MIME_BY_EXTENSION: Readonly<Record<string, string>> = {
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  gif: 'image/gif',
  webp: 'image/webp',
  svg: 'image/svg+xml',
  txt: 'text/plain',
  md: 'text/markdown',
  markdown: 'text/markdown',
  csv: 'text/csv',
  pdf: 'application/pdf',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
}

/** 聊天输入框的文件选择器接受类型：只写 MIME，桌面端才能正确映射成系统文件类型。 */
export const UPLOAD_ACCEPT = [
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
  'text/plain',
  'text/markdown',
  'text/csv',
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
].join(',')

/**
 * 取文件名的小写扩展名（不含点）；没有扩展名时返回空串。
 */
export function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf('.')
  if (dot <= 0 || dot === filename.length - 1) return ''
  return filename.slice(dot + 1).toLowerCase()
}

/**
 * 计算附件最终使用的 MIME：优先用浏览器给的 `file.type`，为空时按扩展名推断。
 */
export function resolveFileMimeType(file: { name: string; type?: string }): string {
  const declared = (file.type || '').trim().toLowerCase()
  if (declared) return declared
  return MIME_BY_EXTENSION[extensionOf(file.name)] || DEFAULT_UPLOAD_MIME
}

/**
 * 上传用的 File：类型缺失但能按扩展名推断时，重建一个带 type 的 File，
 * 保证 FormData 发出的 Content-Type 是后端认可的 MIME。
 */
export function withResolvedMimeType(file: File): File {
  const resolved = resolveFileMimeType(file)
  if (resolved === (file.type || '').toLowerCase()) return file
  if (resolved === DEFAULT_UPLOAD_MIME) return file
  return new File([file], file.name, { type: resolved, lastModified: file.lastModified })
}
