/// <reference types="vite/client" />

// pywebview js_api 桥（仅宿主壳顶层页面可用；浏览器调试模式下不存在）
interface Window {
  pywebview?: {
    api?: {
      open_urls?: (urls: string[]) => Promise<{ opened: number }>
    }
  }
}
