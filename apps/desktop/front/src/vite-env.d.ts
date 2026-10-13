/// <reference types="vite/client" />

// pywebview js_api 桥（仅宿主壳顶层页面可用；浏览器调试模式下不存在）
interface DesktopOpenAppResult {
  ok: boolean
  /** 实际采用的打开方式；inline 表示由前端自己在壳内展开 */
  mode: 'inline' | 'browser' | 'window' | null
  /** browser / window 模式的目标地址，inline 与失败时为 null */
  target: string | null
  /** window 模式是否复用了已开窗口 */
  reused?: boolean
  /** 失败原因：not_found（插件不存在）/ no_base_url（宿主壳地址未知） */
  reason?: string | null
}

interface Window {
  pywebview?: {
    api?: {
      open_urls?: (urls: string[]) => Promise<{ opened: number }>
      open_app?: (appId: string, mode?: string) => Promise<DesktopOpenAppResult>
      /** 关闭当前窗口；主窗口返回 false（前端退化为退出全屏） */
      close_current_window?: () => Promise<boolean>
    }
  }
}
