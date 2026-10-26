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

// 图表引擎必须保持「外置 + 惰性」：内联会让产物从约 0.44M 涨到 3M 以上（mermaid 2.8M + echarts 1.0M）。
// 注意断言方向：产物里引擎只能以**非字面量**动态导入出现，绝不能是字面量 `import("mermaid")`——
// 字面量会被宿主打包器静态解析，没装引擎的宿主在构建/dev 阶段就会报模块解析失败，
// 与「可选依赖、缺失即降级为代码块」的设计相悖（见 src/ui/markdown/optional-engines.ts）。
const engines = ['mermaid', 'echarts']
const engineStatics = {
  from: (engine) => new RegExp(`\\bfrom\\s*["']${engine}["']`),
  bareImport: (engine) => new RegExp(`\\bimport\\s*["']${engine}["']`),
  require: (engine) => new RegExp(`\\brequire\\s*\\(\\s*["']${engine}["']`)
}
const entrySources = [
  packageJson.exports['.'].import,
  packageJson.exports['.'].require
].map((entry) => ({ entry, source: readFileSync(resolve(root, entry), 'utf8') }))

for (const { entry, source } of entrySources) {
  // 取出所有动态导入的说明符文本，用于判断是否被字面量化 / 是否真的引用了引擎
  const dynamicSpecifiers = [...source.matchAll(/\bimport\(([^()]*)\)/g)].map((match) =>
    match[1].trim()
  )
  for (const engine of engines) {
    for (const pattern of Object.values(engineStatics)) {
      if (pattern(engine).test(source)) {
        throw new Error(`Chart engine must not be a static dependency: ${engine} in ${entry}`)
      }
    }
    for (const specifier of dynamicSpecifiers) {
      const literal = specifier.match(/^['"`](.*)['"`]$/)
      if (literal && literal[1] === engine) {
        throw new Error(
          `Chart engine dynamic import must stay non-literal (else host bundlers resolve it eagerly): ${engine} in ${entry}`
        )
      }
    }
    if (!dynamicSpecifiers.some((specifier) => specifier.includes(engine))) {
      throw new Error(`Chart engine must stay external and be imported lazily: ${engine} in ${entry}`)
    }
  }
}
for (const entry of [packageJson.exports['.'].import, packageJson.exports['.'].require]) {
  const size = statSync(resolve(root, entry)).size
  if (size > 1024 * 1024) {
    throw new Error(`Bundle size ${size} exceeds 1MB, chart engines are probably inlined: ${entry}`)
  }
}

console.log(`Package entries verified: ${requiredFiles.join(', ')}`)
