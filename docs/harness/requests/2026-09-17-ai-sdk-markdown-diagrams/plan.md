# 实施计划

## 变更文件

- `apps/ai-sdk/src/ui/markdown/fence-registry.ts`（新增）：围栏渲染器注册表、类型定义、语言归一化、源码长度上限常量。落实 `research.md` 中「统一接缝」的决策。
- `apps/ai-sdk/src/ui/markdown/mermaid-renderer.ts`（新增）：内置 Mermaid 渲染器（引擎三级解析、安全配置、源码清洗、SVG 二次清洗、渲染缓存）。
- `apps/ai-sdk/src/ui/markdown/echarts-renderer.ts`（新增）：内置 ECharts 渲染器（引擎三级解析、仅 JSON 配置、ResizeObserver 生命周期）。
- `apps/ai-sdk/src/ui/markdown/index.ts`（新增）：装配内置渲染器，暴露 `configureMarkdownDiagrams`。
- `apps/ai-sdk/src/ui/components/MarkdownDiagram.vue`（新增）：占位节点宿主组件，负责 loading / rendered / fallback 状态与清理。
- `apps/ai-sdk/src/ui/components/MarkdownContent.vue`（修改）：覆盖 `fence` 渲染规则输出占位节点，新增 `hydrateDiagrams()` 水合与卸载清理。
- `apps/ai-sdk/src/ui/styles.css`（修改）：图表容器、loading、降级代码块样式与深色主题适配。
- `apps/ai-sdk/src/ui/index.ts`（修改）：导出公开 API 与 `MarkdownContent` 组件。
- `apps/ai-sdk/vite.config.ts`（修改）：`rollupOptions.external` 增加 `mermaid`、`echarts`，防止引擎被内联进产物。
- `apps/ai-sdk/README.md`（修改）：新增「Markdown 图表」章节。
- `apps/ai-sdk/src/ui/__tests__/*`（新增 / 扩展）：注册表、渲染器、围栏管线单测。

## 实施步骤

1. 写 `fence-registry.ts`：类型 `MarkdownFenceRenderer` / `MarkdownFenceContext`、`registerMarkdownFenceRenderer` / `getMarkdownFenceRenderer` / `listMarkdownFenceLanguages`、常量 `MAX_DIAGRAM_SOURCE_LENGTH`。
2. 写 `mermaid-renderer.ts`：
   - 引擎解析：注入值（`undefined` 未配置 / `null` 禁用）→ `globalThis.mermaid` → 动态 `import('mermaid')`（非字面量导入，避免 TS 与打包器静态解析）；结果缓存。
   - 源码处理：剔除 `%%{` 与 `click ` 开头的行；超过长度上限或首行不是已知图类型关键字时判定为「未就绪」并降级。
   - 渲染：`initialize({ startOnLoad: false, securityLevel: 'strict', suppressErrorRendering: true, theme, flowchart: { htmlLabels: false, useMaxWidth: true } })` 后 `render(id, code)`，SVG 经 `DOMPurify`（`svg` + `svgFilters` profile）清洗后写入容器。
   - 缓存：以「清洗后源码 + 主题」为键缓存 SVG 字符串。
3. 写 `echarts-renderer.ts`：JSON 解析守卫 + `init/setOption/ResizeObserver/dispose` 生命周期，与 Mermaid 相同的引擎解析顺序。
4. 写 `markdown/index.ts`：注册两个内置渲染器，暴露 `configureMarkdownDiagrams({ mermaid?, echarts?, enabled? })`。
5. 写 `MarkdownDiagram.vue`：`onMounted` / `watch(code, theme)` 触发渲染，用世代计数避免过期结果写 DOM，失败或降级时渲染源码代码块与本地化提示。
6. 改 `MarkdownContent.vue`：保存 `markdown-it` 默认 `fence` 规则作为兜底；命中已注册语言时输出占位 `div`（`data-xxai-diagram-lang` / `data-xxai-diagram-id`），源码写入每次 render 重建的 `Map`；新增 `hydrateDiagrams()` 用 Vue `render()` 挂载组件，卸载时 `render(null, el)` 并清理。
7. 补样式与 README。
8. 写 / 扩展单测，跑 `type-check`、`vitest`、`build`，再做 headless Chrome 冒烟验证。

## 测试步骤

- `cd apps/ai-sdk && npm run type-check` → 预期无类型错误。
- `cd apps/ai-sdk && npx vitest run` → 预期全部通过（含新增用例）。
- `cd apps/ai-sdk && npm run build` → 预期构建成功，产物中不包含内联的 mermaid / echarts。
- 浏览器冒烟：
  - 生成临时页面 `/tmp/diagram-smoke/index.html`，通过 `python3 -m http.server` 提供；
  - 页面加载 `dist/xxai-agent.es.js`，用 `configureMarkdownDiagrams` 注入假 mermaid / echarts 引擎，渲染含 ` ```mermaid `、` ```echarts `、未知语言围栏的 Markdown；
  - `Google Chrome --headless=new --dump-dom --virtual-time-budget=...` 输出 DOM，检查 SVG 是否生成、未知语言是否为代码块、无注入时是否降级。
- `python3 tools/harness/audit.py` → 预期无新增 ERROR。

## 回滚说明

- 本次改动集中在 `apps/ai-sdk/src/ui/markdown/`、`MarkdownContent.vue`、`MarkdownDiagram.vue`、`styles.css`、`ui/index.ts`、`vite.config.ts`、`README.md` 与测试文件；回滚即删除新增目录与文件、还原 `MarkdownContent.vue` / `styles.css` / `ui/index.ts` / `vite.config.ts`。
- 后端、消息协议与数据模型未改动，回滚不涉及数据修复。
- 需特别关注：`fence` 规则改写后未注册语言的代码块行为是否与改动前完全一致。

## 人工确认点

- 架构边界变化（新增公开扩展点 + 依赖策略）已获用户确认（2026-09-17），确认内容见 `spec.md` 变更记录。
- 无其它待确认点。
