#!/usr/bin/env node
/**
 * 一键发布子应用到桌面插件市场。
 *
 * 做的事（以 `pnpm publish:plugin note` 为例）：
 *   读 apps/note/public/manifest.json → 默认 patch 升版本 → pnpm 构建
 *   → 校验 dist 产物版本 → 复制成临时目录 note/（脚本要求目录名 == manifest.id）
 *   → 调 apps/desktop/scripts/make_plugin_release.py 打包 + 更新市场索引
 *   → 提交 manifest、index.json、zip 并推送 main
 *
 * 用法（仓库根目录）：
 *   pnpm publish:plugin note                # 发布 note：patch +1
 *   pnpm publish:plugin note --bump minor   # 升次版本
 *   pnpm publish:plugin note --version 0.3.0
 *   pnpm publish:plugin note --dry-run      # 只预演
 *   pnpm publish:plugin note --no-push      # 只本地提交，不推送
 *   pnpm publish:plugin note --no-bump      # 保持现有版本（内容变了会被脚本拒绝）
 *   pnpm publish:plugin note --no-build     # 跳过构建，用已有 dist
 *
 * 注意：推送后用户端要在「设置 → 插件市场」点刷新，才会看到「更新到 vX」。
 */
import { execFileSync } from 'node:child_process'
import { cpSync, existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const DESKTOP_DIR = path.join(REPO_ROOT, 'apps', 'desktop')
const PLUGIN_RELEASE_SCRIPT = path.join(DESKTOP_DIR, 'scripts', 'make_plugin_release.py')
const MARKET_INDEX = path.join(DESKTOP_DIR, 'market', 'index.json')
const PACKAGES_DIR = path.join(DESKTOP_DIR, 'market', 'packages')
const PYTHON = path.join(DESKTOP_DIR, '.venv', 'bin', 'python')
const MAIN_BRANCH = 'main'

const USAGE = `用法：pnpm publish:plugin <子应用名> [选项]

  子应用名   apps/ 下的目录名，例如 note、ledger
  --bump <major|minor|patch>  版本号递增方式（默认 patch）
  --version <x.y.z>           直接指定版本号，与 --bump / --no-bump 互斥
  --no-bump                   不升版本（内容必须和已发布的一致，否则脚本会拒绝）
  --no-build                  跳过构建，直接用已有 dist
  --no-push                   只本地提交，不推送
  --dry-run                   预演，不落盘
  -h, --help                  显示本帮助`

function fail(message) {
  throw new Error(message)
}

function run(command, args, options = {}) {
  return execFileSync(command, args, { cwd: REPO_ROOT, stdio: 'inherit', ...options })
}

function capture(command, args) {
  return execFileSync(command, args, { cwd: REPO_ROOT, encoding: 'utf8' }).trim()
}

function readJson(file) {
  return JSON.parse(readFileSync(file, 'utf8'))
}

function relative(file) {
  return path.relative(REPO_ROOT, file)
}

function parseArgs(argv) {
  const opts = {
    app: null,
    version: null,
    bump: 'patch',
    bumpEnabled: true,
    build: true,
    gitCommit: true,
    push: true,
    dryRun: false,
    help: false,
  }
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    switch (arg) {
      case '--bump': {
        const value = argv[i + 1]
        if (!value || value.startsWith('--')) fail(`--bump 后面缺少参数\n\n${USAGE}`)
        if (!['major', 'minor', 'patch'].includes(value)) fail(`--bump 只支持 major/minor/patch，收到 ${value}`)
        opts.bump = value
        i += 1
        break
      }
      case '--version':
        opts.version = argv[i + 1] || ''
        if (!opts.version || opts.version.startsWith('--')) fail(`--version 后面缺少参数\n\n${USAGE}`)
        i += 1
        break
      case '--no-bump':
        opts.bumpEnabled = false
        break
      case '--no-build':
        opts.build = false
        break
      case '--no-push':
        opts.push = false
        break
      case '--dry-run':
        opts.dryRun = true
        break
      case '-h':
      case '--help':
        opts.help = true
        break
      default:
        if (arg.startsWith('--')) fail(`不认识的参数：${arg}\n\n${USAGE}`)
        if (opts.app) fail(`只支持发布一个子应用，收到多余参数：${arg}`)
        opts.app = arg
    }
  }
  return opts
}

function parseVersion(version) {
  const text = String(version || '').trim()
  if (!/^\d+(\.\d+){0,2}$/.test(text)) fail(`版本号必须是 x.y.z 形式，收到「${text}」`)
  const parts = text.split('.').map(Number)
  while (parts.length < 3) parts.push(0)
  return parts
}

function formatVersion(parts) {
  return parts.join('.')
}

function bumpVersion(version, part) {
  const parts = parseVersion(version)
  const index = { major: 0, minor: 1, patch: 2 }[part]
  parts[index] += 1
  for (let i = index + 1; i < parts.length; i += 1) parts[i] = 0
  return formatVersion(parts)
}

function compareVersions(left, right) {
  const a = parseVersion(left)
  const b = parseVersion(right)
  for (let i = 0; i < 3; i += 1) {
    if (a[i] !== b[i]) return a[i] > b[i] ? 1 : -1
  }
  return 0
}

function assertCleanIndex() {
  const staged = capture('git', ['diff', '--cached', '--name-only'])
  if (staged) fail(`暂存区里有内容，先提交或 git restore --staged . 再发版：\n${staged}`)
}

function runPnpm(args) {
  const execPath = (process.env.npm_execpath || '').trim()
  const viaPnpmBinary = () => execFileSync('pnpm', args, { cwd: REPO_ROOT, stdio: 'inherit' })
  try {
    if (/\.(c|m)?js$/.test(execPath)) {
      execFileSync(process.execPath, [execPath, ...args], { cwd: REPO_ROOT, stdio: 'inherit' })
    } else {
      viaPnpmBinary()
    }
  } catch (error) {
    if (error.code === 'ENOENT') fail('找不到 pnpm 命令：请确认 pnpm 可用（根 package.json 要求 pnpm@9）')
    fail(`命令执行失败（退出码 ${error.status ?? '?'}）：pnpm ${args.join(' ')}`)
  }
}

function listAppsWithManifest() {
  const appsDir = path.join(REPO_ROOT, 'apps')
  return readdirSync(appsDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .filter((name) => existsSync(path.join(appsDir, name, 'public', 'manifest.json')))
}

function main() {
  const opts = parseArgs(process.argv.slice(2))
  if (opts.help) {
    console.log(USAGE)
    return
  }
  if (!opts.app) fail(`缺少子应用名\n\n${USAGE}`)
  if (opts.version && !opts.bumpEnabled) fail('--version 和 --no-bump 不能同时使用')

  const appDir = path.join(REPO_ROOT, 'apps', opts.app)
  if (!existsSync(appDir)) fail(`目录不存在：apps/${opts.app}`)

  const manifestPath = path.join(appDir, 'public', 'manifest.json')
  if (!existsSync(manifestPath)) {
    const names = listAppsWithManifest()
    fail(
      `apps/${opts.app}/public/manifest.json 不存在，这个目录不是桌面子应用。\n` +
        `可发布的子应用：${names.length ? names.join('、') : '（无）'}`,
    )
  }

  const pkgPath = path.join(appDir, 'package.json')
  if (!existsSync(pkgPath)) fail(`缺少 apps/${opts.app}/package.json`)
  const pkg = readJson(pkgPath)
  if (!pkg.scripts || !pkg.scripts.build) fail(`apps/${opts.app}/package.json 没有 build 脚本，先补上再发布`)

  const manifestText = readFileSync(manifestPath, 'utf8')
  const manifest = JSON.parse(manifestText)
  const id = manifest.id
  if (!id) fail('public/manifest.json 缺少 id')
  if (!/^[a-z0-9][a-z0-9-]*$/.test(id)) fail(`manifest.id「${id}」只能用小写字母、数字、连字符`)
  const oldVersion = String(manifest.version || '')
  if (!oldVersion) fail('public/manifest.json 缺少 version')

  const newVersion = opts.version
    ? formatVersion(parseVersion(opts.version))
    : opts.bumpEnabled
      ? bumpVersion(oldVersion, opts.bump)
      : oldVersion

  if (compareVersions(newVersion, oldVersion) < 0) {
    fail(`新版本 ${newVersion} 比当前 ${oldVersion} 小，市场会拒绝降级`)
  }

  const zipPath = path.join(PACKAGES_DIR, `${id}-${newVersion}.zip`)

  if (opts.dryRun) {
    console.log('▶ 预演：pnpm publish:plugin ' + opts.app)
    console.log(`   子应用：   apps/${opts.app}（manifest.id=${id}）`)
    console.log(`   版本：     ${oldVersion} → ${newVersion}${opts.bumpEnabled ? '' : '（--no-bump，保持不变）'}`)
    console.log(`   构建：     ${opts.build ? `pnpm --dir apps/${opts.app} build` : '跳过'}`)
    console.log(`   打包：     ${relative(zipPath)}`)
    console.log(`   更新索引： ${relative(MARKET_INDEX)}`)
    console.log(`   提交：     apps/${opts.app}/public/manifest.json、apps/desktop/market/index.json、zip`)
    console.log(`   推送：     ${opts.push ? `git push origin ${MAIN_BRANCH}` : '不推送'}`)
    console.log('\n✓ 预演结束，没有改动任何文件。')
    return
  }

  if (opts.gitCommit) assertCleanIndex()
  if (opts.push) {
    const branch = capture('git', ['symbolic-ref', '--short', 'HEAD'])
    if (branch !== MAIN_BRANCH) fail(`当前分支是 ${branch}，市场索引走 ${MAIN_BRANCH} 的 raw 地址；切到 ${MAIN_BRANCH} 或加 --no-push`)
  }

  let released = false
  let restoreManifest = null
  let tmpRoot = null

  try {
    if (newVersion !== oldVersion) {
      manifest.version = newVersion
      writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n', 'utf8')
      restoreManifest = manifestText
      console.log(`▶ 版本号：${oldVersion} → ${newVersion}`)
    }

    if (opts.build) {
      console.log(`▶ 构建：pnpm --dir apps/${opts.app} build`)
      runPnpm(['--dir', `apps/${opts.app}`, 'build'])
    }

    const distDir = path.join(appDir, 'dist')
    const distManifestPath = path.join(distDir, 'manifest.json')
    if (!existsSync(distManifestPath)) fail(`构建后没有 ${relative(distManifestPath)}，检查子应用的构建输出目录`)
    const distManifest = readJson(distManifestPath)
    if (distManifest.id !== id) fail(`dist/manifest.json 的 id（${distManifest.id}）与 public/manifest.json（${id}）不一致`)
    if (String(distManifest.version) !== String(newVersion)) {
      fail(`构建产物版本（${distManifest.version}）与预期（${newVersion}）不一致：确认构建会把 public/ 拷进 dist/`)
    }

    // 发布脚本要求「插件目录名 == manifest.id」，所以先摆成临时目录 <tmp>/<id>/
    tmpRoot = mkdtempSync(path.join(tmpdir(), 'xxai-plugin-'))
    const stageDir = path.join(tmpRoot, id)
    cpSync(distDir, stageDir, { recursive: true })

    if (!existsSync(PYTHON)) fail(`找不到 ${PYTHON}，请先在 apps/desktop 下准备 Python 虚拟环境`)
    if (!existsSync(PLUGIN_RELEASE_SCRIPT)) fail(`找不到 ${relative(PLUGIN_RELEASE_SCRIPT)}`)

    console.log(`▶ 打包并更新索引：make_plugin_release.py（${id} v${newVersion}）`)
    try {
      execFileSync(PYTHON, [PLUGIN_RELEASE_SCRIPT, stageDir], { cwd: DESKTOP_DIR, stdio: 'inherit' })
    } catch (error) {
      fail(`发布脚本执行失败（退出码 ${error.status ?? '?'}）`)
    }
    released = true

    const index = readJson(MARKET_INDEX)
    const entry = (index.plugins || []).find((item) => item.id === id)
    if (!entry) fail('打包成功但索引里没有这个插件条目，检查 market/index.json')
    if (String(entry.version) !== String(newVersion)) fail(`索引版本（${entry.version}）与预期（${newVersion}）不一致`)
    if (!entry.sha256 || !entry.download) fail('索引条目缺少 sha256/download 字段')
    if (!existsSync(zipPath)) fail(`索引已更新但找不到安装包：${relative(zipPath)}`)

    if (!opts.gitCommit) {
      console.log('\n✓ 已完成打包与索引更新（--no-git，未提交）。')
      return
    }

    run('git', ['add', relative(manifestPath), relative(MARKET_INDEX), relative(zipPath)])
    const staged = capture('git', ['diff', '--cached', '--name-only'])
    if (!staged) {
      console.log('\n✓ 内容与已发布版本完全一致，没有需要提交的改动。')
      return
    }

    const message = `chore(release): ${id} v${newVersion}`
    run('git', ['commit', '-m', message])
    console.log(`✓ 已提交：${message}`)

    if (!opts.push) {
      console.log(`\n✓ 本地完成。下一步手动推送：git push origin ${MAIN_BRANCH}`)
      return
    }

    run('git', ['push', 'origin', MAIN_BRANCH])
    const remotes = capture('git', ['remote']).split('\n').map((line) => line.trim())
    if (remotes.includes('gitee')) run('git', ['push', 'gitee', MAIN_BRANCH])

    console.log(`\n✓ 已发布 ${id} v${newVersion} 并推送 ${MAIN_BRANCH}。`)
    console.log('  已装旧版的机器打开「设置 → 插件市场」点刷新，即可看到「更新到 v' + newVersion + '」。')
  } catch (error) {
    if (restoreManifest !== null && !released) {
      writeFileSync(manifestPath, restoreManifest, 'utf8')
      console.log(`↩ 已回滚 apps/${opts.app}/public/manifest.json 的版本号`)
    }
    throw error
  } finally {
    if (tmpRoot) rmSync(tmpRoot, { recursive: true, force: true })
  }
}

try {
  main()
} catch (error) {
  console.error(`\n✗ ${error.message}\n`)
  process.exit(1)
}
