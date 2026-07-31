import { strict as assert } from 'node:assert'
import { internalPageRoutes, resolveInternalRoute } from './routes'

const expectedRoutes = Object.values(internalPageRoutes)

for (const route of expectedRoutes) {
  assert.equal(resolveInternalRoute(route), null)
}

assert.equal(resolveInternalRoute('智能体管理'), '/ai/bots')
assert.equal(resolveInternalRoute(' 模型用量 '), '/ai/model-usage')
assert.equal(resolveInternalRoute('Embed Client 管理'), '/ai/embed-clients')
assert.equal(resolveInternalRoute('外部网站'), null)
assert.equal(resolveInternalRoute('https://example.com'), null)
assert.equal(resolveInternalRoute('/ai/bots'), null)
