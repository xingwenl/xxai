/**
 * 后台会话记录三层页面的真实浏览器验证（由 2026-10-13-admin-conversation-history.sh 调用）。
 *
 * 前置：vite dev server（VITE_PROXY_TARGET 指向本地 uvicorn 实例）。登录态通过往
 * localStorage 写 `chat_token` 注入，与 apps/front/src/lib/http.ts 的约定一致。
 *
 * 环境变量：
 *   E2E_BASE           前端地址，默认 http://localhost:5310
 *   E2E_TOKEN          管理员 access token（必填）
 *   PLAYWRIGHT_MODULE  playwright-core 的导入路径或裸包名，默认 playwright-core
 *   E2E_CHROME         Chromium 可执行文件路径，默认用 playwright 自带的解析结果
 *   E2E_OUT            截图输出目录，默认 /tmp/conv-history-e2e
 */
import { existsSync, readdirSync } from 'node:fs'
import { mkdir } from 'node:fs/promises'

const BASE = process.env.E2E_BASE ?? 'http://localhost:5310'
const TOKEN = process.env.E2E_TOKEN
const OUT = process.env.E2E_OUT ?? '/tmp/conv-history-e2e'
const MODULE = process.env.PLAYWRIGHT_MODULE ?? 'playwright-core'

const { chromium } = await import(MODULE)

/**
 * 解析 Chromium 可执行文件：优先环境变量，其次 playwright 注册表，最后按缓存目录扫描。
 * 本机缓存里可能只装了与 playwright-core 期望版本不同的 chromium（例如 1217 vs 1248），
 * 因此不能只信 executablePath()。
 */
function resolveChrome() {
  const candidates = []
  if (process.env.E2E_CHROME) candidates.push(process.env.E2E_CHROME)
  try {
    candidates.push(chromium.executablePath())
  } catch {
    // 未安装时 executablePath() 会抛错，忽略后走目录扫描。
  }
  const cache = `${process.env.HOME}/Library/Caches/ms-playwright`
  if (existsSync(cache)) {
    const dirs = readdirSync(cache)
      .filter((name) => name.startsWith('chromium-'))
      .sort()
      .reverse()
    for (const dir of dirs) {
      candidates.push(
        `${cache}/${dir}/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`,
      )
      candidates.push(`${cache}/${dir}/chrome-mac/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`)
      candidates.push(`${cache}/${dir}/chrome-linux64/chrome`)
      candidates.push(`${cache}/${dir}/chrome-linux/chrome`)
    }
  }
  return candidates.find((candidate) => candidate && existsSync(candidate))
}

const chromePath = resolveChrome()
if (!chromePath) {
  console.error('  找不到可用的 Chromium：请设置 E2E_CHROME 或先安装 playwright 浏览器。')
  process.exit(2)
}

const failures = []
const pageErrors = []
const consoleErrors = []

function check(name, ok, detail = '') {
  console.log(`${ok ? '  [OK]  ' : '  [FAIL]'} ${name}${detail ? `  ${detail}` : ''}`)
  if (!ok) failures.push(name)
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

await mkdir(OUT, { recursive: true })
console.log(`  前端地址：${BASE}`)
console.log(`  浏览器：${chromePath}`)

const browser = await chromium.launch({ executablePath: chromePath, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })

// 既有问题隔离：authenticated-layout 的悬浮 Agent 桥接会请求 /embed/agent-token，
// 本机（未绑定 embed client）返回 401，而 http 拦截器把 401 当成登出并跳 /sign-in，
// 导致任何后台页面在本地都停留不住。这里给该请求返回假 token，隔离这个既有缺陷。
await context.route('**/api/v1/embed/agent-token**', (route) =>
  route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      code: 0,
      message: 'ok',
      data: { access_token: 'e2e-embed-token', expires_in: 3600 },
    }),
  }),
)

await context.addInitScript((token) => {
  window.localStorage.setItem('chat_token', token)
}, TOKEN)

const page = await context.newPage()
page.on('pageerror', (error) => pageErrors.push(String(error)))
page.on('response', (response) => {
  if (response.status() >= 400) {
    console.log(`    [http ${response.status()}] ${response.request().method()} ${response.url()}`)
  }
})
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text())
})

try {
  console.log('  第一层：/conversations?platform=1（会话主体 + 全部会话）')
  await page.goto(`${BASE}/conversations?platform=1`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('text=会话主体', { timeout: 20000 })
  check('侧栏出现「会话记录」入口', (await page.locator('a[href="/conversations"]').count()) > 0)
  check('标题与 Tab 渲染', (await page.locator('text=会话主体').count()) > 0)

  await page.waitForSelector('table tbody tr', { timeout: 20000 })
  const principalRows = await page.locator('table tbody tr').count()
  check('会话主体表格有数据行', principalRows > 0, `行数=${principalRows}`)

  const firstHref = await page.locator('table tbody tr a').first().getAttribute('href')
  check(
    '主体行链接指向第二层',
    /\/conversations\/(user|end_user)\/\d+/.test(firstHref ?? ''),
    `href=${firstHref}`,
  )
  await page.screenshot({ path: `${OUT}/layer1.png`, fullPage: false })

  console.log('  第二层：会话主体下的会话列表（Vue 岛 ConversationList）')
  try {
    await page.locator('table tbody tr a').first().click({ timeout: 15000 })
  } catch (clickError) {
    console.log(`    点击失败：${clickError}`)
    console.log(`    失败时 url=${page.url()}`)
    await page.screenshot({ path: `${OUT}/click-failed.png`, fullPage: true })
    throw clickError
  }
  await page.waitForURL(/\/conversations\/(user|end_user)\/\d+/, { timeout: 20000 })
  await page.waitForSelector('.xxai-history-list', { timeout: 20000 })
  check('ConversationList 岛已挂载', (await page.locator('.xxai-history-list').count()) > 0)
  await wait(1500)
  const items = await page.locator('.xxai-history-item').count()
  const hintError = await page.locator('.xxai-history-hint--error').count()
  check('会话列表渲染出条目', items > 0, `条目数=${items}`)
  check('列表无加载错误', hintError === 0)
  await page.screenshot({ path: `${OUT}/layer2.png`, fullPage: false })

  console.log('  第三层：会话详情（Vue 岛 ConversationHistory + Agent 过程）')
  await page.locator('.xxai-history-item').first().click()
  await page.waitForURL(/\/conversations\/\d+/, { timeout: 20000 })
  await page.waitForSelector('.xxai-history-thread', { timeout: 20000 })
  await wait(2000)
  const messages = await page.locator('.xxai-chat-message').count()
  const loops = await page.locator('.xxai-agent-loop').count()
  check('消息时间线渲染', messages > 0, `消息数=${messages}`)
  check('Agent 执行过程默认可见', loops > 0, `loop 卡片数=${loops}`)
  check(
    '用量汇总已渲染',
    (await page.locator('text=输入 token').count()) > 0 &&
      (await page.locator('text=合计 token').count()) > 0,
  )
  await page.screenshot({ path: `${OUT}/layer3.png`, fullPage: false })

  if ((await page.getByRole('switch').count()) > 0) {
    const switchButton = page.getByRole('switch').first()
    await switchButton.click()
    await wait(1500)
    const loopsAfter = await page.locator('.xxai-agent-loop').count()
    check('关闭「显示 Agent 执行过程」后 loop 卡片消失', loopsAfter === 0, `剩余=${loopsAfter}`)
  } else {
    check('存在「显示 Agent 执行过程」开关', false)
  }

  console.log('  第一层「全部会话」Tab（同一个 SDK 组件的第二种数据源用法）')
  await page.goto(`${BASE}/conversations?platform=1`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('text=全部会话', { timeout: 20000 })
  await page.locator('text=全部会话').first().click()
  await page.waitForSelector('.xxai-history-list', { timeout: 20000 })
  await wait(2000)
  const allTabItems = await page.locator('.xxai-history-item').count()
  check('「全部会话」Tab 渲染出会话条目', allTabItems > 0, `条目数=${allTabItems}`)
  await page.locator('.xxai-history-item').first().click()
  await page.waitForURL(/\/conversations\/\d+/, { timeout: 20000 })
  await page.waitForSelector('.xxai-history-thread', { timeout: 20000 })
  check('「全部会话」条目点击后进入会话详情', /\/conversations\/\d+/.test(page.url()), page.url())
  await page.screenshot({ path: `${OUT}/layer1-all.png`, fullPage: false })

  const shellHref = await page.locator('a[href="/conversations"]').first().getAttribute('href')
  check('侧栏入口 href 正确', shellHref === '/conversations', `href=${shellHref}`)
} catch (error) {
  console.log(`  [FAIL] 流程异常：${error}`)
  failures.push(`流程异常：${error}`)
  try {
    await page.screenshot({ path: `${OUT}/failure.png`, fullPage: true })
  } catch {
    // 截图失败不影响结论
  }
} finally {
  console.log()
  console.log(`  未捕获的前端异常（pageerror）：${pageErrors.length}`)
  for (const item of pageErrors.slice(0, 5)) console.log(`    - ${item}`)
  console.log(`  控制台 error：${consoleErrors.length}`)
  for (const item of consoleErrors.slice(0, 8)) console.log(`    - ${item.slice(0, 160)}`)
  check('没有未捕获的前端异常', pageErrors.length === 0)
  await browser.close()
}

if (failures.length > 0) {
  console.log()
  console.log(`浏览器验证失败项：${failures.length}`)
  for (const item of failures) console.log(`  - ${item}`)
  process.exit(1)
}
console.log()
console.log(`浏览器验证全部通过：三层页面在真实后端数据下可用（截图见 ${OUT}）。`)
