import { existsSync, readFileSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const packageJson = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8'))
const requiredFiles = [
  packageJson.exports['.'].import,
  packageJson.exports['.'].require,
  packageJson.exports['.'].types,
  packageJson.exports['./style.css']
]

for (const file of requiredFiles) {
  if (!existsSync(resolve(root, file))) {
    throw new Error(`Missing package entry: ${file}`)
  }
}

const distFiles = requiredFiles
  .filter((file) => file.endsWith('.js') || file.endsWith('.cjs'))
  .map((file) => readFileSync(resolve(root, file), 'utf8'))
const forbidden = ['private-token', 'client_secret=', 'EMBED_CLIENT_SECRET=']
const leaked = forbidden.filter((value) => distFiles.some((file) => file.includes(value)))
if (leaked.length > 0) {
  throw new Error(`Sensitive build content found: ${leaked.join(', ')}`)
}

const require = createRequire(import.meta.url)
const sdk = require(resolve(root, packageJson.exports['.'].require))
for (const exportName of ['createAgentClient', 'AgentClient', 'configureMarkdownDiagrams', 'registerMarkdownFenceRenderer']) {
  if (typeof sdk[exportName] !== 'function') {
    throw new Error(`CommonJS export is missing: ${exportName}`)
  }
}

// 图表引擎必须保持外置：内联会让产物从约 0.44M 涨到 3M 以上（mermaid 2.8M + echarts 1.0M）
const engineEntries = {
  mermaid: packageJson.exports['.'].import,
  echarts: packageJson.exports['.'].import
}
for (const [engine, entry] of Object.entries(engineEntries)) {
  const source = readFileSync(resolve(root, entry), 'utf8')
  if (!source.includes(`import("${engine}")`)) {
    throw new Error(`Chart engine must stay external and be imported lazily: ${engine}`)
  }
}
for (const entry of [packageJson.exports['.'].import, packageJson.exports['.'].require]) {
  const size = statSync(resolve(root, entry)).size
  if (size > 1024 * 1024) {
    throw new Error(`Bundle size ${size} exceeds 1MB, chart engines are probably inlined: ${entry}`)
  }
}

console.log(`Package entries verified: ${requiredFiles.join(', ')}`)
