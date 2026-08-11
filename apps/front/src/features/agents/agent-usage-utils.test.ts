import { strict as assert } from 'node:assert'
import { formatNumber, getUsageRanges, percentChange } from './agent-usage-utils'

const ranges = getUsageRanges(7)
assert.equal(ranges.start.length, 10)
assert.equal(ranges.start <= ranges.end, true)
assert.equal(ranges.previousEnd < ranges.start, true)
assert.equal(ranges.previousStart <= ranges.previousEnd, true)
assert.equal(formatNumber(1234567), '1,234,567')
assert.equal(percentChange(120, 100), '+20.0%')
assert.equal(percentChange(80, 100), '-20.0%')
assert.equal(percentChange(100, 0), null)
