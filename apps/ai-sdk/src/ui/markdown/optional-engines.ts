/**
 * 可选图表引擎（mermaid / echarts）的模块名。
 *
 * SDK 把它们当**可选**依赖：宿主没装时对应围栏降级成代码块，装上（或挂到
 * `globalThis`）才渲染成图。因此这里的说明符必须让打包器无法静态求值——
 * 直接写 `const specifier = 'mermaid'` 会被常量折叠回字面量，产物里重新变成
 * 静态的 `import("mermaid")`，React/Vue 宿主就必须安装引擎才能构建或启动 dev
 * server，与"可选"的设计相违背。
 *
 * 放在独立模块的可变对象里按属性取值，跨模块可变性使常量折叠无法穿透。
 */
export const optionalEngineSpecifiers: Record<string, string> = {
  mermaid: 'mermaid',
  echarts: 'echarts'
}
