import { existsSync, readFileSync } from 'node:fs'
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
for (const exportName of ['createAgentClient', 'AgentClient']) {
  if (typeof sdk[exportName] !== 'function') {
    throw new Error(`CommonJS export is missing: ${exportName}`)
  }
}

console.log(`Package entries verified: ${requiredFiles.join(', ')}`)
