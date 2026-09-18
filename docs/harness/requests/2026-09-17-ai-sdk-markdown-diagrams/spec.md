# 设计说明：AI SDK Markdown 内联图表渲染

## 目标

- 解决：`apps/ai-sdk` 聊天消息里的 Markdown 围栏代码块（` ```mermaid ` 等）目前只作为纯文本展示，模型输出的流程图/时序图/架构图无法直接看到。
- 目标用户：引入 `xxai-agent` SDK 的第三方网页宿主；以及后续需要接入其它图表引擎（如 ECharts）的业务开发者。
- 完成后可验证：模型（或宿主注入的消息）返回 ` ```mermaid ` / ` ```echarts ` 围栏时，SDK 在消息气泡内渲染出图表；引擎不可用或语法不完整时，自动降级为原来的代码块展示，消息渲染流程不报错；宿主可用同一接缝注册任意其它语言的渲染器。
- 调研结论引用：依据 `research.md` 最终决策（方案 B），采用「统一围栏渲染器接缝 + 内置 Mermaid 渲染器 + 引擎以可选依赖/显式注入方式加载 + 失败降级代码块」，安全配置对齐 Streamdown 与 Dify 的生产实践（`securityLevel: 'strict'`、`suppressErrorRendering: true`、剔除 `%%{` 与 `click ` 指令）。

## 范围

### SDK `apps/ai-sdk`

- 新增 `src/ui/markdown/fence-registry.ts`：围栏渲染器注册表与公开 API，**语言不做白名单**，任何语言只要注册了渲染器就会被渲染。
  - `registerMarkdownFenceRenderer(language, renderer)`：注册/覆盖某语言的渲染器；`renderer = { language, mount(element, code, context) }`，`mount` 可同步或异步返回卸载清理函数。
  - `getMarkdownFenceRenderer(language)`、`listMarkdownFenceLanguages()`：查询与调试用（语言名按小写归一化）。
  - 未注册语言一律走 `markdown-it` 默认围栏行为，保持代码块展示。
- 新增 `src/ui/markdown/mermaid-renderer.ts`：内置 Mermaid 渲染器。
  - 引擎解析顺序：`configureMarkdownDiagrams({ mermaid })` 注入 → 动态 `import('mermaid')` → `globalThis.mermaid`；全部失败则渲染器返回降级结果，由占位组件展示代码块。
  - 初始化配置：`{ startOnLoad: false, securityLevel: 'strict', suppressErrorRendering: true, theme: <跟随 SDK theme> }`。
  - 源码清洗：按行剔除 `%%{`（init 指令可覆盖配置）与 `click `（可生成 JS 回调/链接）开头的行（对齐 Dify）；超过 `MAX_DIAGRAM_SOURCE_LENGTH` 的源码直接降级并提示。
  - 渲染产物处理：`mermaid.render()` 返回的 SVG 先用 `DOMPurify` 以 `USE_PROFILES: { svg: true, svgFilters: true }` 清洗后再注入容器；按源码哈希缓存渲染结果，避免流式增量重复渲染。
  - 类型自持：不新增 `mermaid` 依赖与类型依赖，本地声明最小接口（`initialize` / `render`），保证在未安装 mermaid 的工程中也能通过类型检查与测试。
- 新增 `src/ui/markdown/echarts-renderer.ts`：内置 ECharts 渲染器（` ```echarts ` 围栏）。
  - 引擎解析顺序与 Mermaid 相同：显式注入 → 动态 `import('echarts')` → `globalThis.echarts`。
  - 只接受 JSON 配置：`JSON.parse` 成功且结果为普通对象才渲染，其余情况降级（对齐 Dify「只接受 JSON，避免执行消息里的任意代码」的做法，不使用 `eval` / `new Function`）。
  - 生命周期：容器内 `init()`，`setOption()` 后用 `ResizeObserver` 跟随容器宽度重绘；清理时断开 observer 并 `dispose()`。
  - 主题：`theme` 为 `dark` 时以 `init(dom, 'dark')` 初始化。
- 新增 `src/ui/markdown/index.ts`：内置渲染器装配与公开聚合入口。
  - `configureMarkdownDiagrams({ mermaid?, echarts?, enabled? })`：显式注入引擎实例（`null` 表示明确禁用该引擎）、或整体关闭图表渲染（关闭后围栏仍显示代码块）。
  - 默认注册 `mermaid` 与 `echarts` 两个内置渲染器。
- 新增 `src/ui/components/MarkdownDiagram.vue`：围栏占位组件的渲染宿主。
  - 状态机：`idle → loading → rendered | fallback`；`fallback` 时渲染原始源码的代码块（保持既有 `xxai-markdown-content` 代码样式）。
  - 主题跟随 SDK 的 `theme` 选项（`light` / `dark` / `auto`），`auto` 时监听 `prefers-color-scheme`。
  - 卸载时调用渲染器返回的清理函数，并中断进行中的渲染（避免卸载后写 DOM）。
- 修改 `src/ui/components/MarkdownContent.vue`：
  - 覆盖 `parser.renderer.rules.fence`：命中已注册语言时输出占位节点 `<div class="xxai-markdown-diagram" data-xxai-diagram-lang="mermaid" data-xxai-diagram-id="xxai-diagram-<n>"></div>`；未命中语言保持 `markdown-it` 默认代码块行为（回归风险为零）。
  - 源码不上 DOM 属性：围栏源码在渲染期写入组件内的 `Map<id, code>`（每次 render 重建），避免转义问题与大段源码进 DOM。
  - 水合：现有 `hydrateImages()` 之外新增 `hydrateDiagrams()`，用 Vue `render(h(MarkdownDiagram, props), el)` 挂载到占位节点，卸载时 `render(null, el)`；渲染顺序与 `watch(html)` 保持一致。
  - `DOMPurify` 配置需允许占位节点与二维码属性（`ADD_ATTR`）通过，且不得放宽 HTML 标签白名单（保持 `html: false` 语义）。
- 修改 `src/ui/styles.css`：新增 `.xxai-markdown-diagram` 容器样式（宽度自适应、水平溢出可横向滚动、loading/降级态样式、深色主题适配），并给 Mermaid SVG 设定 `max-width: 100%`。
- 修改 `apps/ai-sdk/vite.config.ts`：`rollupOptions.external` 增加 `'mermaid'`，使 ES 产物保留裸动态 `import`，UMD 走全局变量/显式注入，避免引擎被内联进主包。
- 修改 `apps/ai-sdk/src/ui/index.ts`：导出 `registerMarkdownFenceRenderer`、`configureMarkdownDiagrams`、`listMarkdownFenceLanguages` 及其类型，并导出 `MarkdownContent` 组件，便于宿主用同一渲染管线渲染任意文本（也用于浏览器冒烟验证）。
- 文档 `apps/ai-sdk/README.md`：新增「Markdown 图表」章节，说明内置语言（`mermaid`、`echarts`）、三种启用方式（`npm i mermaid` / 全局脚本 / 显式注入 `configureMarkdownDiagrams`）、任意语言的注册方法（以 ` ```vega ` 之类第三方引擎为例）、安全边界（不执行模型任意 JS）与降级行为。

### 测试

- `src/ui/__tests__/markdown-content.test.ts` 扩展：围栏渲染管线行为（未注册语言仍是代码块、注册语言输出占位节点、源码不写入 DOM 属性）。
- 新增 `src/ui/__tests__/markdown-fence-registry.test.ts`：注册 / 覆盖 / 语言归一化 / 查询未注册语言返回空。
- 新增 `src/ui/__tests__/markdown-diagram-renderers.test.ts`：Mermaid 源码清洗（`%%{`、`click ` 剔除）、超长源码拒绝、ECharts 仅接受 JSON（JS 表达式、数组、非对象、语法错误全部降级）、引擎解析顺序（注入优先于全局）、`render()` 抛错时降级、清理函数被调用、渲染结果缓存命中不重复渲染。测试全部通过注入假引擎完成，不依赖真实引擎与网络。
- 浏览器冒烟验证：`npm run build` 后用 headless Chrome 加载临时页面，验证真实 DOM 挂载路径（成功渲染 SVG / 引擎缺失时降级为代码块）。

## 非目标

- 不改后端与消息协议：`MessageContentBlock.chart` 类型、`MessageContent.vue` 中 `chart → TableContent` 的既有路由保持不动，结构化图表块留作后续 request。
- 不做 Mermaid 之外的 Markdown 增强（代码高亮、KaTeX 公式、图片放大等）。
- 不做图表导出（PNG/SVG 下载）与交互配置面板（风格切换、缩放）。
- 不改变消息渲染的同步语义：图表渲染是异步增强，失败不影响文本渲染。

## 风险

- 兼容性：`external` 引入后，UMD 产物中 mermaid 不再可用（除非宿主提供全局变量或显式注入）；当前无宿主依赖 UMD + mermaid，但需在 README 明确两种接法的差异。
- 降级路径必须可靠：浏览器直连 `dist/xxai-agent.es.js` 与未安装 mermaid 的工程都会走 `fallback`，表现为「图表显示为代码块」，属预期行为而非报错。
- 流式增量：模型逐字输出时围栏源码频繁变化，可能出现「未闭合语法 → 渲染失败」；通过渲染前完整性预检、按源码哈希缓存、失败时静默降级为代码块并等待下一次变更来解决，需在 `verify.md` 记录实际表现。
- 安全：渲染输入是未受信模型输出。三层防护（引擎 `strict` + 源码指令清洗 + SVG 经 DOMPurify 再清洗）之外的残余风险是引擎自身漏洞，需在 README 标注「SDK 不保证图表引擎的安全修复」，并在 `verify.md` 记录采用的引擎版本。
- 性能：引擎仅在首次出现图表时加载；单条消息图表数量与单图源码长度设上限，避免超长输入拖慢页面。
- 回归：`fence` 规则仅对已注册语言改写，未注册语言走默认分支；`DOMPurify` 仅新增属性白名单，不放宽标签白名单。

## 停点判断

- 是否涉及架构边界变化：是（新增 SDK 公开扩展点 `registerMarkdownFenceRenderer` / `configureMarkdownDiagrams`，并确立「重引擎走可选依赖 + 失败降级」的依赖策略）
- 是否涉及数据模型变化：否
- 是否涉及 API 契约变化：否（仅 SDK 前端渲染层，后端与消息协议不变）
- 是否涉及鉴权或权限行为变化：否
- 结论：因架构边界变化，**进入实现前需人工确认**

## 验收标准

1. `cd apps/ai-sdk && npm run type-check` 通过。
2. `cd apps/ai-sdk && npx vitest run` 通过，新增用例覆盖：未注册语言保持代码块、注册语言输出占位节点、源码清洗规则、超长源码降级、渲染失败降级、卸载清理与缓存命中。
3. `cd apps/ai-sdk && npm run build` 成功，且 `dist/xxai-agent.es.js` 为裸 `import('mermaid')`（引擎未内联），`dist/xxai-agent.es.js` 体积相比改动前增幅不超过 5%（当前基线约 1.1M `dist` 目录）。
4. 浏览器冒烟验证（headless Chrome + 临时页面）：
   - 注入假 mermaid 引擎时，` ```mermaid ` 围栏渲染出 `<svg>`，占位节点被替换且源码不出现在 DOM 文本中；
   - 不注入引擎时，同一围栏稳定降级为代码块，页面无未捕获异常；
   - ` ```echarts ` 围栏在注入假 echarts 引擎时调用 `init`/`setOption`，配置为 JS 表达式时降级为代码块。
5. `apps/ai-sdk/README.md` 包含 Markdown 图表章节，覆盖启用方式、ECharts 自定义示例、安全边界与降级行为。
6. `python3 tools/harness/audit.py` 无本次新增 ERROR。

## 变更记录

### 初始版本

- 时间：2026-09-17
- 变更原因：首次创建 request
- 变更内容：建立「AI SDK Markdown 内联图表渲染」初始设计说明
- 影响章节：全部
- 是否触发人工确认：是（架构边界变化：新增公开扩展点与依赖策略）

### 2026-09-17 第 1 次变更

- 变更原因：用户确认方案（接受「引擎外置 + 失败降级」的依赖策略），并明确「其他语言也要支持」
- 变更内容：
  1. 围栏渲染器不做语言白名单，任意语言注册后即可渲染；
  2. 除内置 `mermaid` 外，新增内置 `echarts` 渲染器（同为注入 / 动态 import / 全局三级解析，仅接受 JSON 配置）；
  3. `configureMarkdownDiagrams` 升级为聚合入口，支持 `{ mermaid, echarts, enabled }`；
  4. `apps/ai-sdk/src/ui/index.ts` 增加 `MarkdownContent` 导出，供宿主复用渲染管线并用于浏览器冒烟验证；
  5. 验收标准改为「浏览器冒烟验证 + 纯逻辑单测」双轨（测试环境为 node，无 DOM 运行时）
- 影响章节：目标、范围、非目标、风险、验收标准
- 是否触发人工确认：是（已获用户确认，2026-09-17）

### 2026-09-17 第 2 次变更（fix）

- 变更原因：用户在 `apps/ai-sdk` dev 页面（localhost:5173）实测「mermaid 可以、echarts 不渲染」，排查出三个实现缺陷
- 变更内容：
  1. 引擎解析结果不再永久缓存：`import()` 失败后清空缓存，宿主在页面后段挂上全局引擎（或脚本加载较慢）时，后续消息可以重试成功；
  2. ECharts 初始化时容器不再 `display:none`：加载态保留画布布局尺寸，避免引擎在 0 尺寸容器上初始化（原先只在渲染完成后才显示画布）；
  3. 降级提示区分具体原因（`engine-missing` / `source-not-ready` / `option-invalid`），不再统一显示「图表渲染不可用」；
  4. ECharts 配置解析容忍 `//`、`/* */` 注释与尾随逗号（按字符串感知的方式做保守归一化，仍然不做任何 JS 执行）。
- 影响章节：范围、风险、验收标准
- 是否触发人工确认：否（原 spec 范围内的缺陷修复，不改变方案与安全边界）
