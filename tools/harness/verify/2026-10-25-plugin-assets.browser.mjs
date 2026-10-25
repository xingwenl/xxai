#!/usr/bin/env node
// Harness v2 端到端探针：宿主「子应用资产」+ 念记粘贴/拖拽图片
//
// 做的事：用临时 HOME 起一个真实的宿主内嵌服务（create_app + uvicorn），把 apps/note/dist
// 装进 ~/.desktop-app/plugins/note，然后用无头 Chrome 打开宿主深链 #/app/note —— 走的是真实
// iframe 注入 SDK 的链路，不是伪造桥。进入念记后：
//   1. 新建一条笔记 → 在 textarea 里派发带 image/webp 文件的 paste 事件
//   2. 断言 sdk.assets.put 真的把图片 POST 到 /api/desktop/plugin-assets/note/，
//      正文里出现站内路径，磁盘上多出 .webp 资产文件
//   3. 切到预览态，断言 <img> 真的加载成功（naturalWidth > 0，说明 GET 端点与缓存头链路通）
//   4. 再用拖拽插入第二张图，断言正文里有两个资产引用
//   5. 粘贴纯文本不产生资产；最后核对 plugin-data 里的正文、资产目录内的文件数与清单一致
//
// 退出码：0 全通过 / 3 未执行（缺 Chrome、缺构建产物）/ 1 有断言失败。
//
// 环境变量：CHROME_BIN、NOTE_ASSETS_PORT（默认 5301）、NOTE_SHOT_DIR（默认 /tmp）。

import { spawn } from 'node:child_process'
import { cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const CHROME =
  process.env.CHROME_BIN ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const PORT = Number(process.env.NOTE_ASSETS_PORT ?? 5301)
const SHOT_DIR = process.env.NOTE_SHOT_DIR ?? '/tmp'

const NOTE_DIST = path.join(ROOT, 'apps/note/dist')
const HOST_DIST = path.join(ROOT, 'apps/desktop/front/dist')
const PYTHON = path.join(ROOT, 'apps/desktop/.venv/bin/python')

const failures = []
let skips = 0
const cleanups = []

function pass(label) {
  console.log(`  ✓ ${label}`)
}

function fail(label, detail) {
  failures.push(label)
  console.log(`  ✗ ${label}${detail ? `（${detail}）` : ''}`)
}

function check(ok, label, detail) {
  if (ok) pass(label)
  else fail(label, detail)
  return ok
}

function skip(reason) {
  console.log(`未执行：${reason}`)
  skips += 1
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function waitFor(fn, { timeout = 15000, interval = 150, label = '条件' } = {}) {
  const deadline = Date.now() + timeout
  let last
  while (Date.now() < deadline) {
    try {
      last = await fn()
      if (last) return last
    } catch (err) {
      last = err
    }
    await sleep(interval)
  }
  throw new Error(`等待超时：${label}（最后一次结果：${last instanceof Error ? last.message : JSON.stringify(last)}）`)
}

// ---------- CDP 最小客户端 ----------

class Cdp {
  constructor(ws) {
    this.ws = ws
    this.nextId = 1
    this.pending = new Map()
    this.exceptions = []
    ws.addEventListener('message', (event) => {
      const msg = JSON.parse(event.data)
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id)
        this.pending.delete(msg.id)
        if (msg.error) reject(new Error(`${msg.error.message} (${msg.error.code})`))
        else resolve(msg.result)
        return
      }
      if (msg.method === 'Runtime.exceptionThrown') {
        const detail = msg.params?.exceptionDetails
        this.exceptions.push(detail?.exception?.description ?? detail?.text ?? 'unknown exception')
      }
      if (msg.method === 'Runtime.consoleAPICalled' && msg.params?.type === 'error') {
        const text = (msg.params.args ?? [])
          .map((arg) => arg.value ?? arg.description ?? arg.type)
          .join(' ')
        this.exceptions.push(`console.error: ${text}`)
      }
    })
  }

  send(method, params = {}) {
    const id = this.nextId++
    this.ws.send(JSON.stringify({ id, method, params }))
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id)
          reject(new Error(`CDP 超时：${method}`))
        }
      }, 20000)
    })
  }

  /** 在页面主上下文里求值；async 表达式会自动 await。 */
  async eval(expression) {
    const result = await this.send('Runtime.evaluate', {
      expression: `(async () => { ${expression} })()`,
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
    })
    if (result.exceptionDetails) {
      throw new Error(
        result.exceptionDetails.exception?.description ?? result.exceptionDetails.text ?? '页面求值异常',
      )
    }
    return result.result?.value
  }

  close() {
    try {
      this.ws.close()
    } catch {
      /* ignore */
    }
  }
}

// ---------- 主流程 ----------

async function main() {
  if (!existsSync(CHROME)) {
    skip(`没找到 Chrome（${CHROME}），端到端探针需要真实浏览器`)
    return
  }
  if (!existsSync(path.join(NOTE_DIST, 'manifest.json')) || !existsSync(path.join(NOTE_DIST, 'index.html'))) {
    skip(`apps/note/dist 不完整，先跑 pnpm --dir apps/note build`)
    return
  }
  if (!existsSync(path.join(HOST_DIST, 'index.html'))) {
    skip(`apps/desktop/front/dist 不完整，先跑宿主前端 build`)
    return
  }
  if (!existsSync(PYTHON)) {
    skip(`没找到宿主 Python 环境（${PYTHON}）`)
    return
  }

  // 临时 HOME：宿主按 Path.home() 解析插件目录/plugin-data/plugin-assets，改 HOME 即可隔离真实用户数据。
  const workDir = mkdtempSync(path.join(tmpdir(), 'note-assets-probe-'))
  cleanups.push(() => rmSync(workDir, { recursive: true, force: true }))
  const homeDir = path.join(workDir, 'home')
  const pluginDir = path.join(homeDir, '.desktop-app/plugins/note')
  mkdirSync(pluginDir, { recursive: true })
  cpSync(NOTE_DIST, pluginDir, { recursive: true })
  const assetDir = path.join(homeDir, '.desktop-app/plugin-assets/note')
  const dataFile = path.join(homeDir, '.desktop-app/plugin-data/note/note.json')
  const shotDir = path.join(SHOT_DIR)
  mkdirSync(shotDir, { recursive: true })

  // ---------- 起真实宿主服务 ----------
  // 内置插件目录故意留空：仓库里的 hello-world 也声明了 tools，会被宿主静默预挂载成隐藏 iframe，
  // 那样「摸到第几个 iframe」就变得不确定。这里只装念记，让端到端断言只面对一个插件。
  const builtinDir = path.join(workDir, 'builtin')
  mkdirSync(builtinDir, { recursive: true })
  const server = spawn(
    PYTHON,
    [
      '-c',
      [
        'import os',
        'import uvicorn',
        'from pathlib import Path',
        'from desktop_app.manager import PluginManager',
        'from desktop_app.server import create_app',
        "manager = PluginManager(builtin_dir=Path(os.environ['PROBE_BUILTIN_DIR']), user_dir=Path.home() / '.desktop-app' / 'plugins')",
        `uvicorn.run(create_app(manager), host='127.0.0.1', port=${PORT}, log_level='warning')`,
      ].join('\n'),
    ],
    {
      cwd: path.join(ROOT, 'apps/desktop'),
      env: {
        ...process.env,
        HOME: homeDir,
        DESKTOP_DEV_AGENT: '',
        PYTHONPATH: path.join(ROOT, 'apps/desktop'),
        PROBE_BUILTIN_DIR: builtinDir,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    },
  )
  cleanups.push(() => server.kill('SIGKILL'))
  let serverLog = ''
  server.stdout.on('data', (chunk) => (serverLog += chunk))
  server.stderr.on('data', (chunk) => (serverLog += chunk))

  const health = await waitFor(
    async () => {
      try {
        const resp = await fetch(`http://127.0.0.1:${PORT}/api/health`)
        return resp.ok ? await resp.json() : null
      } catch {
        return null
      }
    },
    { timeout: 30000, label: '宿主服务 /api/health' },
  ).catch((err) => {
    throw new Error(`${err.message}\n${serverLog.slice(-2000)}`)
  })
  console.log(`宿主服务已就绪：${health.service} ${health.version}（HOME=${homeDir}）`)

  const plugins = await (await fetch(`http://127.0.0.1:${PORT}/api/desktop/plugins`)).json()
  const note = (plugins.items ?? []).find((item) => item.id === 'note')
  check(Boolean(note), '宿主把念记识别为已启用的子应用', JSON.stringify(plugins.items?.map((i) => i.id)))

  // 同一个标签页里用无头 Chrome 打开，避免 pywebview 依赖。
  const profileDir = path.join(workDir, 'chrome-profile')
  mkdirSync(profileDir, { recursive: true })
  const chrome = spawn(
    CHROME,
    [
      '--headless=new',
      // 沙箱与 GPU 在受限环境下会导致 Chrome 进程崩溃、DevTools 连接被 1006 关闭；
      // 开关与仓库里既有的 markdown 探针保持一致。
      '--no-sandbox',
      '--disable-gpu',
      '--disable-dev-shm-usage',
      '--use-mock-keychain',
      '--remote-allow-origins=*',
      '--remote-debugging-port=0',
      `--user-data-dir=${profileDir}`,
      '--no-first-run',
      '--no-default-browser-check',
      '--hide-scrollbars',
      '--window-size=1280,900',
      '--allow-insecure-localhost',
      `http://127.0.0.1:${PORT}/#/app/note`,
    ],
    { stdio: ['ignore', 'pipe', 'pipe'] },
  )
  cleanups.push(() => chrome.kill('SIGKILL'))

  const devtoolsPort = await waitFor(
    () => {
      const portFile = path.join(profileDir, 'DevToolsActivePort')
      if (!existsSync(portFile)) return null
      const first = readFileSync(portFile, 'utf8').split('\n')[0]
      return Number(first) || null
    },
    { timeout: 30000, label: 'Chrome DevToolsActivePort' },
  )

  const targets = await waitFor(
    async () => {
      try {
        const list = await (await fetch(`http://127.0.0.1:${devtoolsPort}/json/list`)).json()
        const page = (Array.isArray(list) ? list : []).find(
          (t) => t.type === 'page' && t.webSocketDebuggerUrl && t.url.includes(String(PORT)),
        )
        return page ?? null
      } catch {
        return null
      }
    },
    { timeout: 30000, label: 'Chrome 页面 target' },
  )

  const ws = new WebSocket(targets.webSocketDebuggerUrl)
  cleanups.push(() => ws.close())
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true })
    ws.addEventListener('error', reject, { once: true })
  })
  const cdp = new Cdp(ws)
  cleanups.push(() => cdp.close())
  await cdp.send('Runtime.enable')
  await cdp.send('Page.enable')

  const page = (expr) => cdp.eval(`return (${expr})`)

  // ---------- 进入念记 ----------
  await waitFor(
    () =>
      page(`(() => {
        const frame = document.querySelector('iframe.plugin-frame')
        if (!frame || !frame.contentDocument) return false
        return !!frame.contentDocument.querySelector('button')
      })()`),
    { timeout: 30000, label: '念记 iframe 加载 + SDK 注入' },
  )
  const sdkOk = await page(`(() => {
    const win = document.querySelector('iframe.plugin-frame').contentWindow
    return !!win.desktop
  })()`)
  check(sdkOk, '念记 iframe 里能看到注入的 window.desktop')

  const permission = await page(`(() => {
    const doc = document.querySelector('iframe.plugin-frame').contentDocument
    return { hasSwitch: !!doc.querySelector('.view-switch'), title: doc.title }
  })()`)
  check(permission.title === '念记', 'iframe 里加载的是念记页面', permission.title)

  // 新建一条笔记：新建后念记会切到编辑态，正文 textarea 出现。
  const created = await page(`(() => {
    const doc = document.querySelector('iframe.plugin-frame').contentDocument
    const button = [...doc.querySelectorAll('button')].find((b) => (b.textContent || '').includes('新建笔记'))
    if (!button) return false
    button.click()
    return true
  })()`)
  check(created, '点「新建笔记」创建空白笔记')

  await waitFor(
    () =>
      page(`(() => {
        const doc = document.querySelector('iframe.plugin-frame').contentDocument
        return !!doc.querySelector('textarea.content-input')
      })()`),
    { timeout: 15000, label: '编辑态正文 textarea' },
  )

  // ---------- 粘贴图片（真实 ClipboardEvent + DataTransfer） ----------
  // 页面里现画一张 WebP：避免仓库里塞二进制测试图，也顺带验证浏览器端 toBlob('image/webp') 路径。
  const pasteResult = await page(`(async () => {
    const doc = document.querySelector('iframe.plugin-frame').contentDocument
    const textarea = doc.querySelector('textarea.content-input')
    const canvas = doc.createElement('canvas')
    canvas.width = 160
    canvas.height = 100
    const ctx = canvas.getContext('2d')
    ctx.fillStyle = '#29463b'
    ctx.fillRect(0, 0, 160, 100)
    ctx.fillStyle = '#f2f2ed'
    ctx.fillRect(16, 16, 96, 48)
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/webp', 0.8))
    const file = new doc.defaultView.File([blob], 'paste.webp', { type: 'image/webp' })
    const data = new doc.defaultView.DataTransfer()
    data.items.add(file)
    textarea.focus()
    const event = new doc.defaultView.ClipboardEvent('paste', {
      clipboardData: data,
      bubbles: true,
      cancelable: true,
    })
    textarea.dispatchEvent(event)
    return { blobType: blob.type, blobBytes: blob.size, fileType: file.type }
  })()`)
  check(pasteResult.blobType === 'image/webp', '浏览器端 canvas 产出 WebP', JSON.stringify(pasteResult))

  const afterPaste = await waitFor(
    async () => {
      const value = await page(`(() => document.querySelector('iframe.plugin-frame').contentDocument.querySelector('textarea.content-input').value)()`)
      return value && value.includes('/api/desktop/plugin-assets/note/') ? value : null
    },
    { timeout: 30000, label: '粘贴图片后正文出现资产路径' },
  ).catch((err) => {
    fail('粘贴图片后正文出现资产路径', err.message)
    return ''
  })
  if (afterPaste) pass('粘贴图片后正文写入站内资产路径')
  check(
    !afterPaste.includes('data:image/'),
    '正文存的是站内路径而不是 base64 data URL',
    afterPaste.slice(0, 120),
  )
  check(/!\[[^\]]*\]\(\/api\/desktop\/plugin-assets\/note\/[a-z0-9]{16}\.(png|jpg|webp|gif)\)/.test(afterPaste), '正文是合法的 Markdown 图片引用', afterPaste.slice(0, 120))

  const firstAssetFiles = existsSync(assetDir) ? readdirSync(assetDir).filter((f) => !f.startsWith('.')) : []
  check(firstAssetFiles.length === 1, '宿主资产目录里落下 1 个文件', `实际 ${firstAssetFiles.length}：${firstAssetFiles.join(',')}`)
  const firstAssetName = firstAssetFiles[0] ?? ''
  check(/^[a-z0-9]{16}\.webp$/.test(firstAssetName), '资产 key 是内容哈希 + WebP 扩展名', firstAssetName)
  if (firstAssetName) {
    const bytes = readFileSync(path.join(assetDir, firstAssetName))
    const isWebp = bytes.subarray(0, 4).toString('latin1') === 'RIFF' && bytes.subarray(8, 12).toString('latin1') === 'WEBP'
    check(isWebp, '落盘文件确实以 RIFF/WEBP 魔数开头', bytes.subarray(0, 12).toString('hex'))
    check(bytes.length <= 2 * 1024 * 1024, '单文件没超过 2 MiB 上限', `${bytes.length} 字节`)
  }

  // ---------- 预览态渲染 ----------
  const switched = await page(`(() => {
    const doc = document.querySelector('iframe.plugin-frame').contentDocument
    const button = [...doc.querySelectorAll('.view-switch button')].find((b) => (b.textContent || '').includes('预览'))
    if (!button) return false
    button.click()
    return true
  })()`)
  check(switched, '切到预览态')

  const imgState = await waitFor(
    () =>
      page(`(() => {
        const doc = document.querySelector('iframe.plugin-frame').contentDocument
        const img = doc.querySelector('.markdown-view img.md-img')
        if (!img) return null
        return { src: img.getAttribute('src'), complete: img.complete, width: img.naturalWidth, height: img.naturalHeight }
      })()`),
    { timeout: 20000, label: '预览态 <img> 出现' },
  ).catch((err) => {
    fail('预览态出现 Markdown 图片', err.message)
    return null
  })
  // 元素出现不等于图已经解码完成：<img> 刚插入时 complete=false、naturalWidth=0，
  // 所以再等一次真正 load 完成的状态。
  const imgLoaded = imgState
    ? await waitFor(
        () =>
          page(`(() => {
            const doc = document.querySelector('iframe.plugin-frame').contentDocument
            const img = doc.querySelector('.markdown-view img.md-img')
            if (!img || !img.complete || img.naturalWidth <= 0) return null
            return { src: img.getAttribute('src'), complete: img.complete, width: img.naturalWidth, height: img.naturalHeight }
          })()`),
        { timeout: 20000, label: '预览态 <img> 解码完成' },
      ).catch((err) => {
        console.log(`  · ${err.message}`)
        return null
      })
    : null
  if (imgState) {
    const finalState = imgLoaded ?? imgState
    check(finalState.width > 0, '图片真的加载成功（naturalWidth > 0）', JSON.stringify(finalState))
    check(
      (finalState.src || '').startsWith('/api/desktop/plugin-assets/note/'),
      '图片 src 是站内资产路径',
      finalState.src,
    )
  }

  await cdp.send('Page.captureScreenshot', { format: 'png' }).then((shot) => {
    writeFileSync(path.join(shotDir, 'note-assets-paste-1280.png'), Buffer.from(shot.data, 'base64'))
    console.log(`  截图：${path.join(shotDir, 'note-assets-paste-1280.png')}`)
  })

  // 缓存头 + nosniff：再发一次真实 HTTP 请求核对（<img> 走的是同一端点）
  const assetResp = await fetch(`http://127.0.0.1:${PORT}${imgState ? imgState.src : ''}`)
  const cacheControl = assetResp.headers.get('cache-control') ?? ''
  check(assetResp.status === 200, 'GET 资产返回 200', String(assetResp.status))
  check(cacheControl.includes('immutable'), '资产响应带长缓存头', cacheControl)
  check((assetResp.headers.get('x-content-type-options') ?? '').toLowerCase() === 'nosniff', '资产响应带 nosniff', assetResp.headers.get('x-content-type-options'))
  check((assetResp.headers.get('content-type') ?? '').startsWith('image/webp'), '资产响应 Content-Type 为 image/webp', assetResp.headers.get('content-type'))

  // ---------- 拖拽第二张图 ----------
  const dropResult = await page(`(async () => {
    const doc = document.querySelector('iframe.plugin-frame').contentDocument
    const editButton = [...doc.querySelectorAll('.view-switch button')].find((b) => (b.textContent || '').includes('编辑'))
    if (!editButton) return { ok: false, reason: '没有编辑按钮' }
    editButton.click()
    await new Promise((resolve) => setTimeout(resolve, 200))
    const zone = doc.querySelector('.content-zone')
    const textarea = doc.querySelector('textarea.content-input')
    if (!zone || !textarea) return { ok: false, reason: '编辑态元素缺失' }
    const canvas = doc.createElement('canvas')
    canvas.width = 120
    canvas.height = 120
    const ctx = canvas.getContext('2d')
    ctx.fillStyle = '#c7d8c9'
    ctx.fillRect(0, 0, 120, 120)
    ctx.strokeStyle = '#29463b'
    ctx.lineWidth = 6
    ctx.strokeRect(6, 6, 108, 108)
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/webp', 0.8))
    const file = new doc.defaultView.File([blob], 'drop.webp', { type: 'image/webp' })
    const data = new doc.defaultView.DataTransfer()
    data.items.add(file)
    const over = new doc.defaultView.DragEvent('dragover', { dataTransfer: data, bubbles: true, cancelable: true })
    zone.dispatchEvent(over)
    const drop = new doc.defaultView.DragEvent('drop', { dataTransfer: data, bubbles: true, cancelable: true })
    zone.dispatchEvent(drop)
    return { ok: true }
  })()`)
  check(dropResult?.ok, '在正文区派发拖拽 drop 事件', JSON.stringify(dropResult))

  const afterDrop = await waitFor(
    async () => {
      const value = await page(`(() => document.querySelector('iframe.plugin-frame').contentDocument.querySelector('textarea.content-input').value)()`)
      const count = (value.match(/\/api\/desktop\/plugin-assets\/note\//g) ?? []).length
      return count >= 2 ? value : null
    },
    { timeout: 30000, label: '拖拽后正文出现第二张图' },
  ).catch((err) => {
    fail('拖拽插入第二张图片', err.message)
    return ''
  })
  if (afterDrop) pass('拖拽插入第二张图片')

  const assetFilesAfterDrop = existsSync(assetDir) ? readdirSync(assetDir).filter((f) => !f.startsWith('.')) : []
  check(assetFilesAfterDrop.length === 2, '两张不同图片落成两个资产文件', `实际 ${assetFilesAfterDrop.length}：${assetFilesAfterDrop.join(',')}`)

  // ---------- 纯文本粘贴不产生资产 ----------
  const textPaste = await page(`(() => {
    const doc = document.querySelector('iframe.plugin-frame').contentDocument
    const textarea = doc.querySelector('textarea.content-input')
    const before = textarea.value
    const data = new doc.defaultView.DataTransfer()
    data.setData('text/plain', '纯文本粘贴不该产生资产')
    textarea.dispatchEvent(new doc.defaultView.ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }))
    return { before, after: textarea.value }
  })()`)
  await sleep(600)
  const assetsAfterText = existsSync(assetDir) ? readdirSync(assetDir).filter((f) => !f.startsWith('.')).length : 0
  check(assetsAfterText === 2, '纯文本粘贴不新增资产文件', `${assetsAfterText} 个`)

  // ---------- plugin-data 落盘 ----------
  const dataState = await waitFor(
    () => {
      if (!existsSync(dataFile)) return null
      const raw = readFileSync(dataFile, 'utf8')
      return raw.includes('/api/desktop/plugin-assets/note/') ? raw : null
    },
    { timeout: 20000, label: 'plugin-data 写入正文' },
  ).catch((err) => {
    fail('正文落进宿主 plugin-data', err.message)
    return null
  })
  if (dataState) {
    const parsed = JSON.parse(dataState)
    const noteContent = (parsed.notes ?? []).map((n) => n.content).join('\n')
    const refs = new Set((noteContent.match(/[a-z0-9]{16}\.(png|jpg|webp|gif)/g) ?? []))
    check(refs.size === 2, 'plugin-data 里的正文引用了 2 个资产 key', [...refs].join(','))
    check(JSON.stringify([...refs].sort()) === JSON.stringify(assetFilesAfterDrop.map((f) => f.replace(/^.*\//, '')).sort()), '正文引用的 key 与磁盘文件一一对应')
    check(!dataState.includes('data:image/'), 'plugin-data 里没有 base64 图片')
  }

  // ---------- console 干净 ----------
  await sleep(500)
  const noisy = cdp.exceptions.filter((line) => !line.includes('favicon'))
  check(noisy.length === 0, '页面无未捕获异常与 console.error', noisy.slice(0, 3).join(' | '))

  const shot = await cdp.send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(path.join(shotDir, 'note-assets-drop-1280.png'), Buffer.from(shot.data, 'base64'))
  console.log(`  截图：${path.join(shotDir, 'note-assets-drop-1280.png')}`)
}

let exitCode = 0
try {
  await main()
} catch (err) {
  failures.push(err instanceof Error ? err.message : String(err))
  console.log(`\n探针异常终止：${err instanceof Error ? err.stack : err}`)
} finally {
  for (const cleanup of cleanups.reverse()) {
    try {
      cleanup()
    } catch {
      /* ignore */
    }
  }
}

if (failures.length > 0) {
  console.log(`\n失败 ${failures.length} 项：`)
  for (const item of failures) console.log(`  - ${item}`)
  exitCode = 1
} else if (skips > 0) {
  console.log(`\n通过（另有 ${skips} 项未执行）`)
  exitCode = 3
} else {
  console.log('\n全部通过')
}
process.exit(exitCode)
