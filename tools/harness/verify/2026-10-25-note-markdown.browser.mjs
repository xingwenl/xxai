// Harness 探针：2026-10-25-note-app / Markdown 预览渲染
//
// 用真实 Chrome（CDP，无第三方依赖）打开 apps/note 的构建产物，验证：
//   1) 预览态真的把 Markdown 渲染成了 DOM（heading / 有序无序列表 / 引用 / 代码块 /
//      行内代码 / 表格 / 加粗 / 删除线 / 任务列表），正文里不再残留 `## `、`**` 源码记号；
//   2) 不产生 <img>（图片降级为占位文本，离线也不发远程请求）、无 script/iframe 等活动内容，
//      外链带 target=_blank + rel=noopener；
//   3) 「编辑 / 预览」切换：按钮与 ⌘E 都能切换，偏好写入 localStorage，切回源码态仍是同一份 Markdown；
//   4) 废纸篓只读预览同样渲染 Markdown；
//   5) 760px 窄宽下无横向溢出。
//
// 退出码：0 通过 / 1 断言失败 / 3 未执行（本机没有 Chrome，或 preview 服务起不来）。
// 依赖：只依赖本机 Chrome + node 内置 fetch/WebSocket（node >= 22），不装任何 npm 包。
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const CHROME = process.env.CHROME_BIN ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const PORT = Number(process.env.NOTE_PREVIEW_PORT ?? 5298)
const APP = `http://localhost:${PORT}/`
const SHOT_DIR = process.env.NOTE_SHOT_DIR ?? '/tmp'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

if (!fs.existsSync(CHROME)) {
  console.log(`未执行：没找到 Chrome（${CHROME}），设置 CHROME_BIN 指向本机 Chrome 后可重跑。`)
  process.exit(3)
}
if (!fs.existsSync(path.join(ROOT, 'apps/note/dist/index.html'))) {
  console.log('未执行：apps/note/dist 不存在，先跑 `pnpm --dir apps/note build`。')
  process.exit(3)
}

const checks = []
const check = (name, pass, detail) => {
  checks.push({ name, pass })
  console.log(`${pass ? '✓' : '✗'} ${name}${pass ? '' : ` ${JSON.stringify(detail)}`}`)
}

// preview 服务：直接托管 dist，和宿主里加载的是同一份产物
const server = spawn('pnpm', ['--dir', 'apps/note', 'exec', 'vite', 'preview', '--port', String(PORT), '--strictPort'], {
  cwd: ROOT,
  stdio: ['ignore', 'pipe', 'pipe'],
})
let serverLog = ''
server.stdout.on('data', (chunk) => {
  serverLog += chunk
})
server.stderr.on('data', (chunk) => {
  serverLog += chunk
})

let chrome
const cleanup = () => {
  try {
    chrome?.kill('SIGKILL')
  } catch {
    /* 已经退出 */
  }
  try {
    server.kill('SIGKILL')
  } catch {
    /* 已经退出 */
  }
}
process.on('exit', cleanup)

let reachable = false
for (let i = 0; i < 60; i += 1) {
  try {
    const res = await fetch(APP)
    if (res.ok) {
      reachable = true
      break
    }
  } catch {
    /* 还没起来 */
  }
  await sleep(250)
}
if (!reachable) {
  console.log('未执行：vite preview 没起来（端口被占用或构建产物缺失）。')
  console.log(serverLog.slice(-1200))
  process.exit(3)
}

const profile = path.join('/tmp', `note-md-chrome-${process.pid}`)
fs.rmSync(profile, { recursive: true, force: true })
chrome = spawn(
  CHROME,
  [
    '--headless=new',
    '--disable-gpu',
    '--no-sandbox',
    '--no-first-run',
    '--no-default-browser-check',
    '--use-mock-keychain',
    '--remote-allow-origins=*',
    `--user-data-dir=${profile}`,
    '--remote-debugging-port=0',
    '--window-size=1280,900',
    '--hide-scrollbars',
    'about:blank',
  ],
  { stdio: 'ignore' },
)

// --remote-debugging-port=0 会让 Chrome 把实际端口写进 DevToolsActivePort
const portFile = path.join(profile, 'DevToolsActivePort')
let debugPort = 0
for (let i = 0; i < 80; i += 1) {
  if (fs.existsSync(portFile)) {
    debugPort = Number(fs.readFileSync(portFile, 'utf8').split('\n')[0])
    if (debugPort) break
  }
  await sleep(150)
}
if (!debugPort) {
  console.log('未执行：Chrome 调试端口没起来。')
  process.exit(3)
}

let targets
for (let i = 0; i < 60; i += 1) {
  try {
    const res = await fetch(`http://127.0.0.1:${debugPort}/json/list`)
    if (res.ok) {
      targets = await res.json()
      break
    }
  } catch {
    /* 还没起来 */
  }
  await sleep(150)
}
const page = targets?.find((t) => t.type === 'page')
if (!page) {
  console.log('未执行：找不到可调试的页面目标。')
  process.exit(3)
}

const ws = new WebSocket(page.webSocketDebuggerUrl)
await new Promise((resolve, reject) => {
  ws.onopen = resolve
  ws.onerror = reject
})
let seq = 0
const pending = new Map()
const consoleErrors = []
ws.onmessage = (event) => {
  const message = JSON.parse(event.data)
  if (message.id && pending.has(message.id)) {
    const item = pending.get(message.id)
    pending.delete(message.id)
    message.error ? item.reject(new Error(JSON.stringify(message.error))) : item.resolve(message.result)
  } else if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
    consoleErrors.push(message.params.args.map((a) => a.value ?? a.description).join(' '))
  } else if (message.method === 'Runtime.exceptionThrown') {
    consoleErrors.push(`exception: ${message.params.exceptionDetails.exception?.description ?? ''}`)
  }
}
const send = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const id = ++seq
    pending.set(id, { resolve, reject })
    ws.send(JSON.stringify({ id, method, params }))
    setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id)
        reject(new Error(`TIMEOUT ${method}`))
      }
    }, 20000)
  })
const evaluate = async (expression) => {
  const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails).slice(0, 400))
  return result.result.value
}
const screenshot = async (file) => {
  const shot = await send('Page.captureScreenshot', { format: 'png' })
  fs.writeFileSync(file, Buffer.from(shot.data, 'base64'))
  console.log(`  截图：${file}`)
}
const clickText = (selector, text) =>
  evaluate(`(() => {
    const el = [...document.querySelectorAll(${JSON.stringify(selector)})].find((n) => n.textContent.trim() === ${JSON.stringify(text)})
    if (!el) return 'not-found'
    el.click()
    return 'ok'
  })()`)
const pressMetaE = async () => {
  for (const type of ['rawKeyDown', 'keyUp']) {
    await send('Input.dispatchKeyEvent', {
      type,
      key: 'e',
      code: 'KeyE',
      windowsVirtualKeyCode: 69,
      nativeVirtualKeyCode: 14,
      modifiers: 4,
    })
  }
}

await send('Page.enable')
await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false })

// 一个把常用 Markdown 语法都用上的样例笔记
const now = new Date().toISOString()
const content = [
  '## 为什么要分抽屉',
  '',
  '把信息**先收进来**再谈整理，比一上来就分类更可持续。',
  '',
  '1. 临时收集：随手记，24 小时内处理',
  '2. 主题笔记：按问题聚合',
  '',
  '> 记笔记的目的不是保存，而是让下一次思考从这里开始。',
  '',
  '### 本周要做的',
  '',
  '- [x] 清空临时收集箱',
  '- [ ] 把「散步地图」补成常青笔记',
  '',
  '参考：[常青笔记法](https://notes.andymatuschak.org/) 与 ~~旧方案~~',
  '',
  '```ts',
  'const drawer = notes.filter((n) => !n.deleted_at)',
  '```',
  '',
  '| 抽屉 | 处理周期 |',
  '| --- | --- |',
  '| 临时收集 | 24 小时 |',
  '',
  '![东京散步路线图](/trip.png)',
].join('\n')

const seed = {
  version: 1,
  categories: ['思考', '灵感', '阅读', '旅行', '工作'],
  updated_at: now,
  notes: [
    {
      id: 'md-1',
      title: '周末整理：知识体系的四个抽屉',
      category: '思考',
      tags: ['知识管理'],
      created_at: now,
      updated_at: now,
      deleted_at: null,
      content,
    },
    {
      id: 'md-2',
      title: '会被删掉的笔记',
      category: '灵感',
      tags: [],
      created_at: now,
      updated_at: now,
      deleted_at: null,
      content: '### 废纸篓里也要能看清**加粗**和列表\n\n- 第一项\n- 第二项',
    },
  ],
}

await send('Page.navigate', { url: APP })
await sleep(1000)
await evaluate(`localStorage.setItem('note:data', ${JSON.stringify(JSON.stringify(seed))}); 'ok'`)
await evaluate(`localStorage.removeItem('note:editor-mode'); 'ok'`)
await send('Page.reload')
await sleep(1500)
await evaluate(`document.querySelectorAll('.note-card')[0].click()`)
await sleep(500)

const initial = await evaluate(`(() => {
  const view = document.querySelector('.markdown-view')
  const scope = view ?? document
  return {
    viewExists: !!view,
    textareaVisible: !!document.querySelector('.content-input'),
    toolbarVisible: !!document.querySelector('.toolbar'),
    activeTab: document.querySelector('.view-switch button.is-active')?.textContent?.trim() ?? null,
    h2: scope.querySelectorAll('h2').length,
    h3: scope.querySelectorAll('h3').length,
    ol: scope.querySelectorAll('ol > li').length,
    ul: scope.querySelectorAll('ul > li').length,
    taskMarker: (() => {
      const li = [...scope.querySelectorAll('li')].find((n) => n.querySelector("input[type='checkbox']"))
      return li ? getComputedStyle(li).listStyleType : null
    })(),
    blockquote: scope.querySelectorAll('blockquote').length,
    preCode: scope.querySelectorAll('pre code').length,
    tableCells: scope.querySelectorAll('td, th').length,
    strong: scope.querySelectorAll('strong').length,
    del: scope.querySelectorAll('del').length,
    checkboxes: scope.querySelectorAll("input[type='checkbox']").length,
    links: [...scope.querySelectorAll('a')].map((a) => ({ target: a.getAttribute('target'), rel: a.getAttribute('rel') })),
    imgTags: scope.querySelectorAll('img').length,
    imagePlaceholders: scope.querySelectorAll('.md-image').length,
    activeContent: scope.querySelectorAll('script, iframe, object, embed').length,
    rawMarkers: scope.textContent.includes('**') || scope.textContent.includes('## '),
  }
})()`)

check('预览态渲染出 .markdown-view，且不显示 textarea', initial.viewExists && !initial.textareaVisible, initial)
check('预览态隐藏 Markdown 工具栏', !initial.toolbarVisible)
check('顶栏高亮在「预览」', initial.activeTab === '预览', initial.activeTab)
check('## → h2、### → h3', initial.h2 >= 1 && initial.h3 >= 1, { h2: initial.h2, h3: initial.h3 })
check('有序/无序列表均渲染为 li', initial.ol === 2 && initial.ul === 2, { ol: initial.ol, ul: initial.ul })
check('引用 / 代码块 / 表格 / 加粗 / 删除线 / 任务列表齐全',
  initial.blockquote >= 1 && initial.preCode >= 1 && initial.tableCells >= 4 && initial.strong >= 1 && initial.del >= 1 && initial.checkboxes >= 2,
  initial)
check('任务列表去掉圆点（不复现「圆点 + 复选框」）', initial.taskMarker === 'none', initial.taskMarker)
check('正文不再残留 ** 与 ## 源码记号', initial.rawMarkers === false)
check('外链 target=_blank 且 rel 含 noopener', initial.links.length >= 1 && initial.links.every((l) => l.target === '_blank' && String(l.rel).includes('noopener')), initial.links)
check('不产生 img，图片降级为占位文本', initial.imgTags === 0 && initial.imagePlaceholders === 1, { img: initial.imgTags, ph: initial.imagePlaceholders })
check('渲染结果里没有 script/iframe 等活动内容', initial.activeContent === 0)

await screenshot(path.join(SHOT_DIR, 'note-markdown-1280.png'))

check('点击「编辑」切回源码态', (await clickText('.view-switch button', '编辑')) === 'ok')
await sleep(300)
const editState = await evaluate(`(() => ({
  textarea: !!document.querySelector('.content-input'),
  toolbar: !!document.querySelector('.toolbar'),
  markdown: !!document.querySelector('.markdown-view'),
  stored: localStorage.getItem('note:editor-mode'),
  head: document.querySelector('.content-input')?.value?.slice(0, 8) ?? null,
}))()`)
check('编辑态出现 textarea 与工具栏、隐藏渲染视图', editState.textarea && editState.toolbar && !editState.markdown, editState)
check('切换后偏好写入 localStorage', editState.stored === 'edit', editState.stored)
check('切回源码态仍是同一份 Markdown', editState.head === '## 为什么要分', editState.head)

await evaluate(`document.querySelector('.content-input').focus(); 'ok'`)
await pressMetaE()
await sleep(300)
const afterShortcut = await evaluate(`(() => ({
  textarea: !!document.querySelector('.content-input'),
  markdown: !!document.querySelector('.markdown-view'),
  stored: localStorage.getItem('note:editor-mode'),
  h2: document.querySelectorAll('.markdown-view h2').length,
}))()`)
check('⌘E 切回预览态并重新渲染', !afterShortcut.textarea && afterShortcut.markdown && afterShortcut.h2 >= 1, afterShortcut)
check('⌘E 也持久化偏好', afterShortcut.stored === 'preview', afterShortcut.stored)

await send('Emulation.setDeviceMetricsOverride', { width: 760, height: 900, deviceScaleFactor: 1, mobile: false })
await sleep(400)
const narrow = await evaluate(`(() => ({
  overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  viewWidth: Math.round(document.querySelector('.markdown-view')?.getBoundingClientRect().width ?? 0),
  cols: getComputedStyle(document.querySelector('.app-shell')).gridTemplateColumns,
}))()`)
check('760px 下预览态无横向溢出', narrow.overflow <= 0, narrow)
await screenshot(path.join(SHOT_DIR, 'note-markdown-760.png'))

await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false })
await sleep(200)
const trashFlow = await evaluate(`(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  document.querySelectorAll('.note-card')[1]?.click()
  await sleep(400)
  document.querySelector('.menu-wrap button')?.click()
  await sleep(250)
  const del = [...document.querySelectorAll('[role="menuitem"]')].find((n) => n.textContent.includes('废纸篓'))
  if (!del) return { deleted: false }
  del.click()
  await sleep(700)
  document.querySelector('button.nav-row[aria-label="废纸篓"]')?.click()
  await sleep(700)
  document.querySelector('.note-card')?.click()
  await sleep(500)
  const view = document.querySelector('.markdown-view.trash-preview')
  return {
    deleted: true,
    trashView: !!view,
    h3: view?.querySelectorAll('h3').length ?? 0,
    strong: view?.querySelectorAll('strong').length ?? 0,
    li: view?.querySelectorAll('li').length ?? 0,
    rawMarkers: (view?.textContent ?? '').includes('###'),
  }
})()`)
check('废纸篓只读预览同样渲染 Markdown', trashFlow.trashView && trashFlow.h3 >= 1 && trashFlow.strong >= 1 && trashFlow.li >= 2 && trashFlow.rawMarkers === false, trashFlow)
if (trashFlow.trashView) await screenshot(path.join(SHOT_DIR, 'note-markdown-trash.png'))

check('全程无 console 报错', consoleErrors.length === 0, consoleErrors.slice(0, 3))

const failed = checks.filter((c) => !c.pass)
console.log(`\n${checks.length - failed.length}/${checks.length} 项通过`)
ws.close()
cleanup()
process.exit(failed.length ? 1 : 0)
