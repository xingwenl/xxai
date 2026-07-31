import { createRequire } from 'node:module'
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const root = join(fileURLToPath(new URL('.', import.meta.url)), '..')
const packageJson = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))

function packedFiles() {
  const output = execFileSync('npm', ['pack', '--dry-run', '--json'], {
    cwd: root,
    encoding: 'utf8',
    env: { ...process.env, npm_config_cache: '/tmp/ai-sdk-npm-cache' }
  })
  return JSON.parse(output)[0].files.map(({ path }) => path)
}

test('发布包包含公共类型依赖和 CSS 入口', () => {
  const files = packedFiles()
  const declarationFiles = [
    'dist/index.d.ts',
    'dist/core/index.d.ts',
    'dist/core/types.d.ts',
    'dist/ui/index.d.ts',
    'dist/ui/components/ChatWidget.vue.d.ts'
  ]

  for (const file of declarationFiles) {
    expect(files).toContain(file)
  }
  expect(packageJson.exports['./style.css']).toBe('./dist/style.css')
})

test('CommonJS 入口暴露公共 SDK API', () => {
  const requireEntry = packageJson.exports['.'].require
  expect(requireEntry.endsWith('.cjs')).toBe(true)
  expect(existsSync(join(root, requireEntry))).toBe(true)

  const sdk = require(join(root, requireEntry))
  expect(typeof sdk.createAgentClient).toBe('function')
  expect(typeof sdk.AgentClient).toBe('function')
})

test('发布命令会先构建并验证包', () => {
  expect(packageJson.scripts.prepublishOnly).toBe(
    'npm run build && npm run verify-package'
  )
})
