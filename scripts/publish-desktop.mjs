#!/usr/bin/env node
/**
 * 一键发布桌面主应用（apps/desktop）。
 *
 * 内部就是在 apps/desktop 下跑 scripts/make_release.py，但默认动作已经配好：
 *   版本号 bump → 构建前端 + PyInstaller 打包 → 写 releases/latest.json
 *   → 提交 4 个版本文件并打 desktop-vX tag → 上传 GitHub/Gitee Release → 推送 main 和 tag
 *
 * 用法（仓库根目录）：
 *   pnpm publish:desktop                    # 默认 patch，构建、提交、上传、推送全做
 *   pnpm publish:desktop --bump minor       # 升次版本号
 *   pnpm publish:desktop --version 0.2.6    # 直接指定版本号
 *   pnpm publish:desktop --notes "修复插件市场刷新"
 *   pnpm publish:desktop --dry-run          # 只预演，不改文件、不推送
 *   pnpm publish:desktop --check-only       # 只检查清单一致性
 *   pnpm publish:desktop --no-push          # 只本地提交打 tag，不推送
 *   pnpm publish:desktop --no-publish       # 不传 Release，只出包 + 提交
 *   pnpm publish:desktop --no-build         # 复用已有 dist 产物
 *
 * 安全约束：
 *   - 只提交 make_release.py 负责的版本文件，工作区其他改动不会被带进提交；
 *     但会先要求暂存区为空，避免你自己 staged 的内容被一起提交。
 *   - 上传目标按已保存的令牌自动选择（GitHub / Gitee / 两个都传），
 *     都没配置时降级为只出包并给出提示（可用 --token-status 查看）。
 *   - 若 GitHub 在推送前就建好了 tag，推送 tag 被拒会自动 force 更新到本次提交。
 */
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const DESKTOP_DIR = path.join(REPO_ROOT, 'apps', 'desktop')
const RELEASE_SCRIPT = path.join(DESKTOP_DIR, 'scripts', 'make_release.py')
const PYTHON = path.join(DESKTOP_DIR, '.venv', 'bin', 'python')
const APP_CONFIG = path.join(DESKTOP_DIR, 'desktop_app', 'app_config.py')
const MAIN_BRANCH = 'main'
const TAG_GLOB = 'desktop-v*'

const USAGE = `用法：pnpm publish:desktop [选项]

  --bump <major|minor|patch>  版本号递增方式（默认 patch）
  --version <x.y.z>           直接指定版本号，与 --bump 互斥
  --notes <文本>              Release 说明（默认「桌面版本 vX」）
  --no-build                  跳过构建，复用已有 dist 产物
  --no-git                    不提交、不打 tag（只出包/上传）
  --no-publish                不上传 Release（只出包 + 提交）
  --no-push                   不推送 main / tag
  --dry-run                   预演，不落盘不推送
  --check-only                只检查版本与清单一致性后退出
  -h, --help                  显示本帮助`

function fail(message) {
  console.error(`\n✗ ${message}\n`)
  process.exit(1)
}

function run(command, args, options = {}) {
  return execFileSync(command, args, { cwd: REPO_ROOT, stdio: 'inherit', ...options })
}

function capture(command, args) {
  return execFileSync(command, args, { cwd: REPO_ROOT, encoding: 'utf8' }).trim()
}

function parseArgs(argv) {
  const opts = {
    bump: 'patch',
    bumpGiven: false,
    version: null,
    notes: null,
    build: true,
    gitCommit: true,
    publish: 'auto',
    push: true,
    dryRun: false,
    checkOnly: false,
    help: false,
  }
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    const takeValue = () => {
      const value = argv[i + 1]
      if (!value || value.startsWith('--')) fail(`${arg} 后面缺少参数\n\n${USAGE}`)
      i += 1
      return value
    }
    switch (arg) {
      case '--bump':
        opts.bump = takeValue()
        opts.bumpGiven = true
        if (!['major', 'minor', 'patch'].includes(opts.bump)) fail(`--bump 只支持 major/minor/patch，收到 ${opts.bump}`)
        break
      case '--version':
        opts.version = takeValue()
        break
      case '--notes':
        opts.notes = takeValue()
        break
      case '--publish':
        opts.publish = takeValue()
        break
      case '--no-build':
        opts.build = false
        break
      case '--no-git':
        opts.gitCommit = false
        break
      case '--no-publish':
        opts.publish = 'none'
        break
      case '--no-push':
        opts.push = false
        break
      case '--dry-run':
        opts.dryRun = true
        break
      case '--check-only':
        opts.checkOnly = true
        break
      case '-h':
      case '--help':
        opts.help = true
        break
      default:
        fail(`不认识的参数：${arg}\n\n${USAGE}`)
    }
  }
  return opts
}

/** 读已保存的 Release 令牌，判断哪些托管平台可用。 */
function detectableHosts() {
  const env = {
    github: Boolean((process.env.GITHUB_TOKEN || process.env.GH_TOKEN || '').trim()),
    gitee: Boolean((process.env.GITEE_TOKEN || '').trim()),
  }
  let saved = {}
  try {
    saved = JSON.parse(readFileSync(path.join(homedir(), '.desktop-app', 'release-tokens.json'), 'utf8'))
  } catch {
    saved = {}
  }
  return {
    github: env.github || Boolean(saved.github),
    gitee: env.gitee || Boolean(saved.gitee),
  }
}

function resolvePublishMode(opts) {
  if (opts.publish !== 'auto') {
    if (!['none', 'github', 'gitee', 'all'].includes(opts.publish)) {
      fail(`--publish 只支持 none/github/gitee/all，收到 ${opts.publish}`)
    }
    return opts.publish
  }
  const hosts = detectableHosts()
  if (hosts.github && hosts.gitee) return 'all'
  if (hosts.github) return 'github'
  if (hosts.gitee) return 'gitee'
  console.log('⚠ 没有检测到 GitHub/Gitee 令牌，本次只出包 + 提交，不上传 Release。')
  console.log('  需要上传时先跑一次：cd apps/desktop && .venv/bin/python scripts/make_release.py --set-github-token')
  return 'none'
}

function currentVersion() {
  const text = readFileSync(APP_CONFIG, 'utf8')
  const match = text.match(/^APP_VERSION\s*=\s*["']([^"']+)["']/m)
  return match ? match[1] : ''
}

function listReleaseTags() {
  const out = capture('git', ['tag', '--list', TAG_GLOB])
  return out ? out.split('\n').map((line) => line.trim()).filter(Boolean) : []
}

function assertCleanIndex() {
  const staged = capture('git', ['diff', '--cached', '--name-only'])
  if (staged) {
    fail(`暂存区里有内容，先提交或 git restore --staged . 再发版：\n${staged}`)
  }
}

function currentBranch() {
  return capture('git', ['symbolic-ref', '--short', 'HEAD'])
}

function pushTag(tag) {
  try {
    run('git', ['push', 'origin', tag])
  } catch {
    console.log(`⚠ 远端已存在 tag ${tag}（通常是创建 Release 时自动建的），强制更新到本次提交`)
    run('git', ['push', 'origin', tag, '--force'])
  }
}

function main() {
  const opts = parseArgs(process.argv.slice(2))
  if (opts.help) {
    console.log(USAGE)
    return
  }
  if (opts.version && opts.bumpGiven) fail('--version 和 --bump 不能同时使用')
  if (!existsSync(RELEASE_SCRIPT)) fail(`找不到 ${RELEASE_SCRIPT}`)
  if (!existsSync(PYTHON)) fail(`找不到 ${PYTHON}，请先在 apps/desktop 下准备 Python 虚拟环境`)

  if (opts.checkOnly) {
    run(PYTHON, [RELEASE_SCRIPT, '--check-only'], { cwd: DESKTOP_DIR })
    return
  }

  if (!opts.dryRun && opts.gitCommit) assertCleanIndex()
  if (!opts.dryRun && opts.push && currentBranch() !== MAIN_BRANCH) {
    fail(`当前分支是 ${currentBranch()}，发版推送只允许在 ${MAIN_BRANCH} 上（或加 --no-push）`)
  }

  const publishMode = resolvePublishMode(opts)
  const tagsBefore = listReleaseTags()

  const pyArgs = [RELEASE_SCRIPT]
  if (opts.version) pyArgs.push('--set-version', opts.version)
  else pyArgs.push('--bump', opts.bump)
  if (opts.build) pyArgs.push('--build')
  if (opts.gitCommit) pyArgs.push('--git')
  pyArgs.push('--publish', publishMode)
  if (opts.notes) pyArgs.push('--notes', opts.notes)
  if (opts.dryRun) pyArgs.push('--dry-run')

  console.log(`\n▶ 发布桌面主应用：pnpm 调用 make_release.py（${opts.version ? `--set-version ${opts.version}` : `--bump ${opts.bump}`}，publish=${publishMode}）\n`)
  run(PYTHON, pyArgs, { cwd: DESKTOP_DIR })

  const version = currentVersion()
  const newTags = listReleaseTags().filter((tag) => !tagsBefore.includes(tag))

  if (opts.dryRun) {
    console.log(`\n✓ 预演完成：版本 ${version}，没有改动文件、没有推送。`)
    return
  }
  if (!opts.push) {
    console.log('\n✓ 本地发布完成。下一步手动推送：')
    console.log(`   git push origin ${MAIN_BRANCH}`)
    for (const tag of newTags) console.log(`   git push origin ${tag}`)
    return
  }

  console.log('\n▶ 推送 main 与 tag')
  run('git', ['push', 'origin', MAIN_BRANCH])
  for (const tag of newTags) pushTag(tag)

  console.log(`\n✓ 桌面 v${version} 已发布并推送。`)
  if (publishMode !== 'none') {
    console.log(`  Release: https://github.com/xingwenl/xxai/releases/tag/desktop-v${version}`)
  }
}

main()
