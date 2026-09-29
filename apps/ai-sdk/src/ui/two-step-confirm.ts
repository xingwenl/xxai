import { ref } from 'vue'

/** 二次确认的默认保持时长：超时未再点即自动取消，避免「早就忘了」的误操作。 */
export const TWO_STEP_CONFIRM_TIMEOUT_MS = 3000

/** 待确认目标的标识：固定动作名用字符串，列表行可直接用会话 ID（数字）。 */
export type TwoStepConfirmKey = string | number

/**
 * 「点两次才生效」的确认状态机。
 *
 * 用于删除这类不可逆操作：第一次点击只把目标置为待确认（UI 展示「确认？」），
 * 在超时窗口内对**同一目标**再点一次才返回 `true`。目标用字符串标识，因此
 * 同一套逻辑既能服务「清除聊天记录」这种固定动作，也能服务列表里逐行的
 * 「删除会话」——后者还要求同一时刻只有一个目标处于待确认态（切换到新目标
 * 会重置上一个，避免两行同时挂着「确认？」）。
 *
 * 该函数是纯状态机，不注册任何生命周期钩子：定时器清理由调用方在
 * `onUnmounted` 里调 `cancel()` 完成，这样它也能在组件外被直接测试。
 */
export function useTwoStepConfirm(timeoutMs = TWO_STEP_CONFIRM_TIMEOUT_MS) {
  const pendingKey = ref<string | null>(null)
  let timer: ReturnType<typeof setTimeout> | null = null
  // 数字 ID 与字符串动作名统一按字符串比较，避免 1 与 '1' 被当成两个目标。
  const normalize = (key: TwoStepConfirmKey) => String(key)

  /** 取消待确认态（超时、切换目标、组件卸载、列表刷新时调用）。 */
  function cancel() {
    if (timer !== null) clearTimeout(timer)
    timer = null
    pendingKey.value = null
  }

  function isPending(key: TwoStepConfirmKey) {
    return pendingKey.value === normalize(key)
  }

  /**
   * 请求执行带确认的操作。
   *
   * @returns `true` 表示这是对同一目标的第二次点击，调用方可以真正执行操作；
   *          `false` 表示本次只是把目标置为待确认（或刚重置了别的目标）。
   */
  function confirm(key: TwoStepConfirmKey): boolean {
    const target = normalize(key)
    if (pendingKey.value === target) {
      cancel()
      return true
    }
    cancel()
    pendingKey.value = target
    timer = setTimeout(cancel, timeoutMs)
    return false
  }

  return { pendingKey, isPending, confirm, cancel }
}
