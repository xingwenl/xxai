// React 子应用视图：按注册表渲染 manifest.type === "react" 的应用

import { REACT_APPS, type ReactAppProps } from '../lib/react-apps'

export default function ReactAppView({ appId, theme }: { appId: string } & ReactAppProps) {
  const App = REACT_APPS[appId]
  if (!App) {
    return (
      <div className="h-full flex items-center justify-center gap-2 text-[13px]" style={{ color: 'var(--muted-foreground)' }}>
        <span>🧩</span>
        该应用缺少 React 组件注册
      </div>
    )
  }
  return <App theme={theme} />
}
