// 子应用运行态：宿主壳层可见的「它到底跑起来没有」信号。
//
// 与 manifest.enabled（用户意图）不同，这里记录的是事实：iframe 是否加载、
// SDK 是否注入成功、方法是否注册上。设置页据此提示「已启用但没跑起来」。
// 形态与 tool-bridge 一致：模块级 Map + 订阅，供 useSyncExternalStore 使用。

export type RuntimeStatus =
  | { state: 'idle' }
  | { state: 'ready'; tools: number }
  | { state: 'failed'; reason: string }

const statuses = new Map<string, RuntimeStatus>()
const listeners = new Set<() => void>()

function notify(): void {
  for (const listener of listeners) {
    try {
      listener()
    } catch (err) {
      console.error('[runtime-status] 监听器异常', err)
    }
  }
}

/** 更新某子应用的运行态；状态未变化时不触发订阅者。 */
export function setRuntimeStatus(pluginId: string, status: RuntimeStatus): void {
  const current = statuses.get(pluginId)
  if (
    current?.state === status.state &&
    (status.state !== 'failed' || (current.state === 'failed' && current.reason === status.reason)) &&
    (status.state !== 'ready' || (current.state === 'ready' && current.tools === status.tools))
  ) {
    return
  }
  statuses.set(pluginId, status)
  notify()
}

/** 读取某子应用的运行态；从未上报过视为 idle。 */
export function getRuntimeStatus(pluginId: string): RuntimeStatus {
  return statuses.get(pluginId) ?? { state: 'idle' }
}

/** 订阅任何子应用运行态变化（返回取消订阅函数）。 */
export function subscribeRuntimeStatus(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
