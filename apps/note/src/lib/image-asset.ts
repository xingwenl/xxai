/**
 * 笔记图片：客户端压缩 → 上传为宿主「插件资产」→ 正文里只留同源站内路径。
 *
 * 为什么不在正文里塞 base64：宿主 plugin-data 单值只有 256 KiB，一张截图就撑满，
 * 且每次自动保存都要重写全部图片字节。二进制交给宿主的 plugin-assets 目录，
 * 正文只存 `![](/api/desktop/plugin-assets/note/<key>)`，重启与换窗口都还在。
 *
 * 边界：磁盘上的图只有宿主内能看（不存绝对地址、不做图床）；压到长边 ≤1600 的 WebP
 * 是为了让「单文件 2 MiB」成为兜底门槛而不是常态。GIF 直传不转码，避免动图丢帧。
 */
import type { DesktopBridge, DesktopPluginAsset } from './desktop'

/** 压缩后长边上限：1600 够看清截图文字，又能把 3MB 截图压到几百 KB。 */
export const MAX_EDGE = 1600
/** 首选 WebP 质量：肉眼几乎无损，体积约为 PNG 的 1/5。 */
export const WEBP_QUALITY = 0.8
/** 压缩后仍超上限时的重试质量。 */
export const FALLBACK_QUALITY = 0.6
/** 资产在正文里的引用前缀（站内绝对路径，同源可直接给 <img>）。 */
export const ASSET_PREFIX = '/api/desktop/plugin-assets/note/'
/** 宿主单文件上限：2 MiB。宿主会按原始字节再校验一次，这里只是提前拦。 */
export const MAX_UPLOAD_BYTES = 2 * 1024 * 1024

/** 允许进入压缩流程的输入类型；其余（含 svg）原样交给宿主按魔数拒绝。 */
const COMPRESSIBLE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif'])
/** 正文中资产引用的匹配：16 位十六进制 key + 位图扩展名。 */
const ASSET_KEY_PATTERN =
  /\/api\/desktop\/plugin-assets\/note\/([a-z0-9]{16}\.(?:png|jpg|webp|gif))/g

interface DecodedImage {
  source: CanvasImageSource
  width: number
  height: number
  /** 释放 ImageBitmap / object URL，避免长时间预览多张图时泄漏。 */
  release: () => void
}

/** 解码文件为可绘制对象：优先 createImageBitmap，缺失时回退 <img> + object URL。 */
async function decodeImage(file: File): Promise<DecodedImage> {
  if (typeof createImageBitmap === 'function') {
    const bitmap = await createImageBitmap(file)
    return {
      source: bitmap,
      width: bitmap.width,
      height: bitmap.height,
      release: () => bitmap.close(),
    }
  }

  const url = URL.createObjectURL(file)
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const element = new Image()
      element.onload = () => resolve(element)
      element.onerror = () => reject(new Error('图片无法解码'))
      element.src = url
    })
    return {
      source: image,
      width: image.naturalWidth,
      height: image.naturalHeight,
      release: () => URL.revokeObjectURL(url),
    }
  } catch (error) {
    URL.revokeObjectURL(url)
    throw error
  }
}

/** canvas.toBlob 的 Promise 包装；不支持时返回 null 由调用方回退。 */
function canvasToBlob(canvas: HTMLCanvasElement, type: string, quality: number): Promise<Blob | null> {
  return new Promise<Blob | null>((resolve) => {
    if (typeof canvas.toBlob !== 'function') {
      resolve(null)
      return
    }
    try {
      canvas.toBlob((blob) => resolve(blob), type, quality)
    } catch {
      resolve(null)
    }
  })
}

/** 编码画布：优先 WebP，浏览器不支持时回退 JPEG（老 Safari 会把 webp 编成 png 或返回 null）。 */
async function encodeCanvas(canvas: HTMLCanvasElement, quality: number): Promise<Blob> {
  const webp = await canvasToBlob(canvas, 'image/webp', quality)
  if (webp && webp.type === 'image/webp') return webp

  const jpeg = await canvasToBlob(canvas, 'image/jpeg', quality)
  if (jpeg) return jpeg
  throw new Error('图片转码失败，请换一张图片再试')
}

/**
 * 压缩图片文件：长边超过 1600 时等比缩小，优先输出 WebP q0.8。
 *
 * - GIF 与非白名单类型原样返回：GIF 转码会只剩第一帧；svg 等交给宿主按白名单拒绝，
 *   客户端不做「看起来支持、上传才发现不行」的假承诺。
 * - 解码失败也原样返回：让上传环节给出宿主的真实原因，比在这里猜更准。
 */
export async function compressImageFile(file: File): Promise<Blob> {
  const type = (file.type || '').toLowerCase()
  if (!COMPRESSIBLE_TYPES.has(type)) return file
  // 动图直传：canvas 只保留首帧，压了就丢了动画
  if (type === 'image/gif') return file

  let decoded: DecodedImage
  try {
    decoded = await decodeImage(file)
  } catch {
    return file
  }

  try {
    const longest = Math.max(decoded.width, decoded.height)
    const scale = longest > MAX_EDGE ? MAX_EDGE / longest : 1
    const width = Math.max(1, Math.round(decoded.width * scale))
    const height = Math.max(1, Math.round(decoded.height * scale))

    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const context = canvas.getContext('2d')
    if (!context) return file
    // 缩图用高质量插值，否则截图里的中文会明显发虚
    context.imageSmoothingEnabled = true
    context.imageSmoothingQuality = 'high'
    context.drawImage(decoded.source, 0, 0, width, height)

    let blob = await encodeCanvas(canvas, WEBP_QUALITY)
    if (blob.size > MAX_UPLOAD_BYTES) blob = await encodeCanvas(canvas, FALLBACK_QUALITY)
    if (blob.size > MAX_UPLOAD_BYTES) {
      throw new Error('图片压缩后仍超过 2 MiB，请裁剪或换一张再试')
    }
    return blob
  } finally {
    decoded.release()
  }
}

/** 把上传异常翻译成可给用户看的中文提示，避免把宿主内部报错原样甩到界面上。 */
function formatUploadError(error: unknown): string {
  const detail = error instanceof Error ? error.message : String(error ?? '')
  if (/权限|permission|denied/i.test(detail)) {
    return '当前桌面端没有图片权限，请确认「念记」已允许资产（assets）权限'
  }
  if (/2 ?MiB|too large|413|过大|超出.*上限/i.test(detail)) {
    return '图片太大，单张上限 2 MiB，请裁剪后再试'
  }
  if (/配额|64 ?MiB|500|quota/i.test(detail)) {
    return '图片空间已满，请先彻底删除一些旧笔记（或清空废纸篓）再试'
  }
  return detail ? `图片保存失败：${detail}` : '图片保存失败，请稍后重试'
}

/** 资产地址收敛：宿主返回站内绝对路径就直接用，否则按约定前缀拼 key。 */
function assetUrlOf(asset: DesktopPluginAsset): string {
  const raw = typeof asset.url === 'string' ? asset.url.trim() : ''
  if (raw.startsWith('/')) return raw
  return `${ASSET_PREFIX}${asset.key}`
}

/**
 * 上传一张图片并返回可直接插进正文的 Markdown 片段（alt 统一用「图片」）。
 * 调用前应先用 isAssetsUsable 判断能力，这里只负责「压缩 → put → 拼片段」。
 */
export async function uploadImageFile(
  file: File,
  bridge: DesktopBridge | null,
): Promise<string> {
  if (!bridge?.assets) {
    throw new Error('当前桌面端不支持图片，请升级到 0.2.5 及以上版本')
  }

  const blob = await compressImageFile(file)
  const mime = blob.type || file.type || 'application/octet-stream'

  let asset: DesktopPluginAsset
  try {
    asset = await bridge.assets.put(blob, { mime })
  } catch (error) {
    throw new Error(formatUploadError(error))
  }
  if (!asset || typeof asset.key !== 'string' || !asset.key) {
    throw new Error('图片保存失败：宿主没有返回资产 key')
  }

  return `![图片](${assetUrlOf(asset)})`
}

/** 收集正文里引用的资产 key（去重）；远程图与外链不匹配，天然被忽略。 */
export function extractAssetKeys(markdown: string): string[] {
  if (typeof markdown !== 'string' || !markdown) return []
  const keys = new Set<string>()
  // 全局正则带 lastIndex 状态，每次调用新建实例，避免跨调用串味
  const pattern = new RegExp(ASSET_KEY_PATTERN.source, 'g')
  let match = pattern.exec(markdown)
  while (match !== null) {
    if (match[1]) keys.add(match[1])
    match = pattern.exec(markdown)
  }
  return [...keys]
}

/**
 * 回收孤儿资产：拿「剩余所有笔记正文」的引用集合与宿主资产列表比对，删掉没被引用的。
 *
 * 回收是尽力而为：任何一步失败只告警不抛，绝不能因为删图失败挡住「删除笔记」主流程。
 * 返回实际删除的资产数量（供界面提示与验证断言）。
 */
export async function gcAssets(
  bridge: DesktopBridge | null,
  remainingContents: string[],
): Promise<number> {
  try {
    if (!bridge?.assets) return 0
    if (typeof bridge.assets.list !== 'function' || typeof bridge.assets.delete !== 'function') {
      return 0
    }

    const referenced = new Set<string>()
    for (const content of remainingContents) {
      for (const key of extractAssetKeys(content ?? '')) referenced.add(key)
    }

    const assets = await bridge.assets.list()
    if (!Array.isArray(assets)) return 0

    let removed = 0
    for (const asset of assets) {
      const key = asset?.key ?? ''
      if (!key || referenced.has(key)) continue
      try {
        await bridge.assets.delete(key)
        removed += 1
      } catch (error) {
        console.warn('[note] 回收图片失败，跳过', key, error)
      }
    }
    return removed
  } catch (error) {
    console.warn('[note] 回收图片失败', error)
    return 0
  }
}
