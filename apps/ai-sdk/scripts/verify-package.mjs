import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const packageJson = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8'))
const requiredFiles = [
  packageJson.exports['.'].import,
  packageJson.exports['.'].require,
  packageJson.exports['.'].types
]

for (const file of requiredFiles) {
  if (!existsSync(resolve(root, file))) {
    throw new Error(`Missing package entry: ${file}`)
  }
}

const distFiles = requiredFiles
  .filter((file) => file.endsWith('.js'))
  .map((file) => readFileSync(resolve(root, file), 'utf8'))
const forbidden = ['private-token', 'client_secret=', 'EMBED_CLIENT_SECRET=']
const leaked = forbidden.filter((value) => distFiles.some((file) => file.includes(value)))
if (leaked.length > 0) {
  throw new Error(`Sensitive build content found: ${leaked.join(', ')}`)
}

console.log(`Package entries verified: ${requiredFiles.join(', ')}`)
