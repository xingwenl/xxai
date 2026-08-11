const DAY_MS = 24 * 60 * 60 * 1000

function toDateInput(value: Date) {
  return value.toISOString().slice(0, 10)
}

export type UsageRange = {
  start: string
  end: string
  previousStart: string
  previousEnd: string
}

export function getUsageRanges(days: 7 | 30): UsageRange {
  const end = new Date()
  const start = new Date(end.getTime() - (days - 1) * DAY_MS)
  const previousEnd = new Date(start.getTime() - DAY_MS)
  const previousStart = new Date(start.getTime() - days * DAY_MS)
  return {
    start: toDateInput(start),
    end: toDateInput(end),
    previousStart: toDateInput(previousStart),
    previousEnd: toDateInput(previousEnd),
  }
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value)
}

export function percentChange(current: number, previous: number): string | null {
  if (previous === 0) return null
  const delta = ((current - previous) / previous) * 100
  return `${delta >= 0 ? '+' : ''}${delta.toFixed(1)}%`
}
