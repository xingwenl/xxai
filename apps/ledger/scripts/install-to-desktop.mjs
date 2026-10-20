#!/usr/bin/env node
/**
 * 把 apps/ledger/dist 安装到桌面宿主的插件目录。
 *
 * 用法：
 *   node scripts/install-to-desktop.mjs               # 安装到 ~/.desktop-app/plugins/ledger
 *   node scripts/install-to-desktop.mjs --zip         # 先打 zip，再安装
 *   node scripts/install-to-desktop.mjs --target DIR  # 自定义安装目录
 *   node scripts/install-to-desktop.mjs --json        # 只输出机器可读结果，便于脚本断言
 *
 * 只同步本插件自己的目录，不会动 ~/.desktop-app/plugins 下的其他插件。
 */
import { cpSync, existsSync, mkdirSync, rmSync, statSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { homedir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const PLUGIN_ID = 'ledger'
const PLUGIN_NAME = '记账'
const PLUGIN_VERSION = '0.1.0'

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url))
const APP_ROOT = path.resolve(SCRIPT_DIR, '..')
const DIST_DIR = path.join(APP_ROOT, 'dist')
const DEFAULT_TARGET = path.join(homedir(), '.desktop-app', 'plugins', PLUGIN_ID)

const USAGE = `用法：node scripts/install-to-desktop.mjs [--zip] [--target <目录>] [--json]

  --zip            构建产物先打包成 ledger-${PLUGIN_VERSION}.zip
  --target <目录>   自定义安装目录（默认 ~/.desktop-app/plugins/${PLUGIN_ID}）
  --json           只输出 {"installedTo": "...", "zip": "..."}，便于脚本断言
  -h, --help       显示本帮助`

/** 统一的中文错误退出：错误信息走 stderr，退出码 1。 */
function fail(message) {
  console.error(`[ledger] ${message}`)
  process.exit(1)
}

/** 把 ~ 展开成用户主目录，方便直接传 --target ~/somewhere。 */
function expandHome(value) {
  if (value === '~') return homedir()
  if (value.startsWith(`~${path.sep}`)) return path.join(homedir(), value.slice(2))
  return value
}

function parseArgs(argv) {
  const options = { zip: false, json: false, target: null, help: false }
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg === '--zip') options.zip = true
    else if (arg === '--json') options.json = true
    else if (arg === '-h' || arg === '--help') options.help = true
    else if (arg === '--target') {
      const value = argv[index + 1]
      if (!value) fail('--target 需要一个目录参数')
      options.target = value
      index += 1
    } else if (arg.startsWith('--target=')) {
      options.target = arg.slice('--target='.length)
    } else {
      fail(`未知参数：${arg}\n\n${USAGE}`)
    }
  }
  return options
}

function assertDistReady() {
  if (!existsSync(DIST_DIR) || !statSync(DIST_DIR).isDirectory()) {
    fail(`未找到构建产物：${DIST_DIR}\n请先运行 pnpm --dir apps/ledger build`)
  }
  for (const file of ['index.html', 'manifest.json']) {
    if (!existsSync(path.join(DIST_DIR, file))) {
      fail(`构建产物不完整：缺少 ${file}（${DIST_DIR}）\n请先运行 pnpm --dir apps/ledger build`)
    }
  }
}

/** 打包到 dist 的上级目录，返回 zip 绝对路径。 */
function buildZip() {
  const zipPath = path.resolve(DIST_DIR, '..', '..', `ledger-${PLUGIN_VERSION}.zip`)
  try {
    rmSync(zipPath, { force: true })
    // 在 dist 内执行，保证压缩包内是 index.html / assets 这类相对根路径
    execFileSync('zip', ['-r', '-q', zipPath, '.'], { cwd: DIST_DIR, stdio: 'ignore' })
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error)
    fail(`打包 zip 失败：${reason}\n请确认系统已安装 zip 命令（macOS/Linux 通常自带）`)
  }
  return zipPath
}

function resolveTarget(rawTarget) {
  const target = rawTarget ? path.resolve(expandHome(rawTarget)) : DEFAULT_TARGET
  const root = path.parse(target).root
  if (target === root) fail(`安装目录不合法：${target}`)
  // 防止把构建产物目录或项目目录本身删掉
  if (target === DIST_DIR || target === APP_ROOT || DIST_DIR.startsWith(`${target}${path.sep}`)) {
    fail(`安装目录不合法：${target}（会覆盖构建产物目录）`)
  }
  if (target.startsWith(`${DIST_DIR}${path.sep}`)) fail(`安装目录不合法：${target}（位于 dist 内部）`)
  return target
}

function install(target) {
  try {
    mkdirSync(path.dirname(target), { recursive: true })
    // 先清空目标目录再整体拷贝：避免上次构建残留的旧文件被宿主继续加载
    rmSync(target, { recursive: true, force: true })
    cpSync(DIST_DIR, target, { recursive: true })
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error)
    fail(`安装到 ${target} 失败：${reason}`)
  }
}

function main() {
  const options = parseArgs(process.argv.slice(2))
  if (options.help) {
    console.log(USAGE)
    return
  }

  assertDistReady()
  const target = resolveTarget(options.target)
  const zipPath = options.zip ? buildZip() : null

  install(target)

  if (options.json) {
    console.log(JSON.stringify({ installedTo: target, zip: zipPath }))
    return
  }

  console.log(`[ledger] 已安装到 ${target}`)
  if (zipPath) console.log(`[ledger] 压缩包：${zipPath}`)
  console.log(`重启桌面应用后可在应用页看到「${PLUGIN_NAME}」`)
}

main()
