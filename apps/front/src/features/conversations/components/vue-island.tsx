import { useEffect, useRef } from 'react'
import { createApp } from 'xxai-agent'

/** xxai-agent 主入口导出的 Vue 组件类型；宿主不依赖 vue，类型从 createApp 推导。 */
export type VueIslandComponent = Parameters<typeof createApp>[0]

/**
 * 把 xxai-agent 的 Vue 组件挂成 React 页面里的一个「岛」。
 *
 * 只负责挂载与卸载：组件内部的分页、加载态、错误提示由 Vue 自己维护，React 侧不参与其
 * 响应式更新。props 在挂载那一刻快照，`depKey` 变化时整体重建，这样既避免了向已挂载实例
 * 透传 props 的复杂度，也保证筛选条件变化后组件内部状态（页码）回到初始值。
 */
export function VueIsland({
  component,
  props,
  depKey,
  className,
}: {
  component: VueIslandComponent
  props: Record<string, unknown>
  depKey: string
  className?: string
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const propsRef = useRef(props)

  // React Compiler 不允许在渲染期写 ref，改在 effect 里同步最新 props；
  // 挂载 effect 声明在后，因此它读到的始终是本次渲染的 props。
  useEffect(() => {
    propsRef.current = props
  })

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const app = createApp(component, { ...propsRef.current })
    app.mount(container)
    return () => app.unmount()
  }, [component, depKey])

  return <div ref={containerRef} className={className} />
}
