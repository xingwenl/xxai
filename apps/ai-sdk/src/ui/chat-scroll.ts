export type ScrollMetrics = {
  scrollTop: number
  scrollHeight: number
  clientHeight: number
}

export function isNearScrollBottom(metrics: ScrollMetrics, threshold = 48): boolean {
  const distance = metrics.scrollHeight - metrics.clientHeight - metrics.scrollTop
  return distance <= threshold
}
