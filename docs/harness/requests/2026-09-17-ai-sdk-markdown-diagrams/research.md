# 业界调研记录

## 调研问题

- 本次要解决什么问题：`apps/ai-sdk` 的消息 Markdown 目前只渲染文本、表格、图片，模型输出的 ` ```mermaid ` / ` ```echarts ` 围栏只以纯文本代码块展示，无法看到图表。
- 调研结果将影响哪些范围、架构、接口或实现决策：
  - 是否在 SDK 内引入图表引擎依赖，以及与宿主工程的依赖边界
  - Markdown 渲染管线（`markdown-it` 渲染规则 + `DOMPurify` 清洗）如何接入异步渲染的图表
  - 未受信模型输出渲染为 SVG/Canvas 的安全边界
  - 流式增量消息下的渲染时机与降级策略

## 功能复杂度

- 级别：普通业务功能（涉及渲染管线扩点、可选依赖策略、安全边界，但不改数据模型与后端契约）
- 选择理由：仅影响 `apps/ai-sdk` 前端渲染层，但会新增公开扩展接口与依赖策略，且渲染内容来自模型输出（未受信输入）
- 最低调研要求：至少一个权威来源 + 一个成熟案例；补充安全与性能调研
- 调研方式说明：本次执行环境网络被限制（`curl` 访问官方站点失败，见「调研限制」），改用**本机已安装/已 checkout 的引擎源码与成熟项目源码**作为一手依据，官方文档在线核对列为剩余风险

## 参考依据

### 来源 1

- 类型：官方源码（依赖包）
- 名称：`markdown-it` 15.0.0 渲染器规则实现（`default_rules.fence`）
- 链接：`apps/ai-sdk/node_modules/markdown-it/dist/markdown-it.mjs`（包内 `dist`，对应 https://github.com/markdown-it/markdown-it）
- 版本或发布日期：15.0.0（本项目 `apps/ai-sdk/package.json` 依赖）
- 调研日期：2026-09-17
- 核心做法：`fence` token 的默认规则签名为 `(tokens, idx, options, env, slf)`；`token.info` 给出围栏语言（`langName = info.split(/(\s+)/g)[0]`），默认输出 `<pre><code class="language-xxx">`；通过 `md.renderer.rules.fence = ...` 可整体替换围栏渲染，`md.renderer.rules.image` 也是同一机制。
- 对本项目的启发：`MarkdownContent.vue` 已经用同一机制改写 `image` 规则，围栏渲染可以沿用「渲染期产出占位节点 + 挂载后水合」的既有模式，无需引入 markdown-it 插件体系或第二套解析器。

### 来源 2

- 类型：官方源码（引擎包）
- 名称：Mermaid 11.12.3 运行时（配置项、按图类型懒加载 chunk、体积）
- 链接：`/Users/lixingwen/xw/git/BuildingAI-master/node_modules/.pnpm/mermaid@11.12.3/node_modules/mermaid`（对应 https://mermaid.js.org/）
- 版本或发布日期：11.12.3
- 调研日期：2026-09-17
- 核心做法：
  - 入口 `dist/mermaid.core.mjs` 仅 44K，通过 `import("./chunks/mermaid.core/flowDiagram-*.mjs")` 等语句按图类型懒加载，`dist/chunks` 未压缩合计约 35M，`dist/mermaid.min.js` 单文件 2.8M
  - 提供 `initialize(config)` / `render(id, code)` 两段式 API；`securityLevel`（strict/loose/sandbox）、`suppressErrorRendering`、`maxTextSize` 等安全相关配置存在运行时常量
  - `render()` 返回 `{ svg }` 字符串，由调用方注入 DOM
- 对本项目的启发：引擎本身支持懒加载与严格安全级别，适合「按需加载 + 只渲染完成态」的接入方式；但单文件 2.8M，直接打进 SDK 会显著放大产物（当前 SDK `dist` 仅 1.1M）。

### 来源 3

- 类型：成熟开源项目（生产实现）
- 名称：Dify Web `mermaid` 渲染组件与 `markdown-blocks/code-block.tsx`
- 链接：`/Users/lixingwen/xw/git/dify/web/app/components/base/mermaid/index.tsx`、`utils.ts`、`app/components/base/markdown-blocks/code-block.tsx`（Dify commit `5c0d3c4393`，2026-09-07；`mermaid` 版本 11.17.2）
- 版本或发布日期：本地 checkout 快照，抓取日期 2026-09-17
- 调研日期：2026-09-17
- 核心做法：
  - 按围栏语言分派：`case 'mermaid'` 渲染图表组件，`case 'echarts'` 渲染 ECharts
  - 组件用 `dynamic(() => import(...), { ssr: false })` 懒加载，避免首屏和 SSR 成本
  - 初始化配置：`startOnLoad: false`、`securityLevel: 'strict'`、`maxTextSize: 50000`，另有流程图 `htmlLabels: true`、主题（light/dark）色板与 SVG 主题后处理
  - 针对「模型输出是不可信输入」做了源码清洗：按行过滤 `%%{` 开头（Mermaid init 指令可覆盖配置）与 `click ` 开头（可生成 JS 回调/链接），并在注释中明确说明理由
  - 流式场景做了「代码是否完整」的启发式判断（`isMermaidCodeComplete`）与渲染重试（`waitForDOMElement`），渲染失败回退提示；SVG 注入前仅做 `<br>` → `<br/>` 归一化
  - ECharts 分支只接受 `JSON.parse` 解析的配置对象，注释明确「只接受 JSON，避免执行消息里的任意代码」
- 对本项目的启发：这是 LLM 聊天场景最贴近的成熟参考——引擎由宿主应用安装、渲染器懒加载、严格安全级别 + 源码清洗 + 只接受 JSON 配置。本项目的差别在于 SDK 由第三方页面引入，无法假设宿主已经安装引擎，因此需要「注入/可选依赖 + 失败降级」。

### 来源 4

- 类型：成熟开源项目（流式 Markdown 渲染器）
- 名称：`@streamdown/mermaid` 1.0.2（Vercel Streamdown 的 Mermaid 插件）
- 链接：`/Users/lixingwen/xw/git/BuildingAI-master/node_modules/.pnpm/@streamdown+mermaid@1.0.2_react@19.2.4/node_modules/@streamdown/mermaid/dist/index.js`
- 版本或发布日期：1.0.2（peer `mermaid@^11.12.2`）
- 调研日期：2026-09-17
- 核心做法：把引擎抽成独立插件包（`mermaid` 仅作为 peer 依赖），插件默认配置为 `{ startOnLoad: false, theme: 'default', securityLevel: 'strict', fontFamily: 'monospace', suppressErrorRendering: true }`，通过 `mermaid.render()` 输出 SVG，支持 `createMermaidPlugin({ config })` 覆盖配置。
- 对本项目的启发：把重引擎放在主包之外、以 peer/可选依赖方式提供，是流式聊天渲染器的主流做法；`suppressErrorRendering: true` 可避免 Mermaid 把错误 SVG 直接写进页面，利于统一降级。

### 来源 5

- 类型：官方源码（依赖包）
- 名称：DOMPurify 3.4.13 的 profile 支持
- 链接：`apps/ai-sdk/node_modules/dompurify/dist/purify.es.mjs`
- 版本或发布日期：3.4.13
- 调研日期：2026-09-17
- 核心做法：`USE_PROFILES` 支持 `html` / `svg` / `svgFilters` / `mathMl` / `text` 组合；开启 `svg` 与 `svgFilters` 时会把 SVG 标签与滤镜标签加入白名单，同时保留 `svgDisallowed` 黑名单处理。
- 对本项目的启发：现有 `{ html: true }` 会剥掉 SVG；若要清洗 Mermaid 输出或在同一管线内保留 SVG，需要显式开启 `svg`/`svgFilters`，或在独立容器中注入 SVG。

### 来源 6

- 类型：官方源码（依赖包，体积与用法参考）
- 名称：Apache ECharts 5.4.0
- 链接：`/Users/lixingwen/xw/sibo/ui/node_modules/echarts/package.json`、`dist/echarts.min.js`
- 版本或发布日期：5.4.0
- 调研日期：2026-09-17
- 核心做法：`echarts.min.js` 单文件 1.0M，`init(dom)` + `setOption(option)` 的命令式 API，`option` 为纯 JSON 结构（Dify 也据此只接受 JSON）。
- 对本项目的启发：ECharts 的接入形态与 Mermaid 不同（需要真实 DOM 容器 + 生命周期管理 + resize 处理），但同样可以通过「围栏语言 → 渲染器」的统一接缝接入，无需写进 SDK 核心。

### 来源 7

- 类型：生产实践（本仓库构建约束）
- 名称：`apps/ai-sdk/vite.config.ts` lib 模式构建
- 链接：`apps/ai-sdk/vite.config.ts`
- 版本或发布日期：仓库当前版本
- 调研日期：2026-09-17
- 核心做法：同时产出 ES（`xxai-agent.es.js`）与 UMD（`xxai-agent.umd.cjs`），当前 `external: []`（连 Vue 都打进包）；`demo/*.html` 既有 `import '../dist/xxai-agent.es.js'` 的浏览器直连用法，也有 `<script src="../dist/xxai-agent.umd.cjs">` 用法。
- 对本项目的启发：UMD 无法做 code-split，动态 `import()` 的重引擎在 UMD 下要么被内联（体积暴涨），要么必须走全局变量；浏览器直连 ESM 场景也无法解析裸模块名，所以「加载失败即降级为代码块」是必须的兜底，不能把图表渲染设成消息渲染的强依赖。

### 来源 8

- 类型：同类 Agent 项目实现（参考对比）
- 名称：Pi `packages/coding-agent/src/modes/interactive/components/mermaid.ts`
- 链接：`/Users/lixingwen/xw/git/pi/packages/coding-agent/src/modes/interactive/components/mermaid.ts`
- 版本或发布日期：本机源码快照，调研日期 2026-09-17
- 核心做法：在终端场景用 `grok-mermaid` 把 Mermaid 源码渲染成 ASCII/Unicode 文本，再以代码跨度形式塞回 Markdown 输出，属于「图形 → 文本」的降级式渲染。
- 对本项目的启发：对应到 Web 场景，结论是「降级形态应当始终可用」——渲染引擎不可用时保留源码代码块，用户仍能复制/阅读图表定义。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：SDK 直接内置 Mermaid，围栏触发动态 `import()` 打包成 chunk | 开箱即用，宿主零配置 | 单文件 2.8M；UMD 无法 code-split 会把引擎内联进主包；SDK 被引擎版本锁定；浏览器直连 ESM 场景 chunk 路径依赖发布产物 | 中（体积与构建约束与本仓库现状冲突） |
| 方案 B：提供统一「围栏渲染器」接缝 + 内置 Mermaid 渲染器，引擎走「显式注入 → 动态 `import('mermaid')` → `globalThis.mermaid`」三级解析，失败降级代码块；`vite` 将 `mermaid` 外置 | SDK 体积几乎不变；安装 `mermaid` 的宿主开箱即用；未安装/离线场景优雅降级；同一接缝可接 ECharts 等其它引擎；与 Streamdown（插件化）、Dify（引擎属宿主）思路一致 | 需要宿主安装或注入引擎；UMD 需全局脚本或显式注入；三级解析需要明确文档与 warning | 高 |
| 方案 C：只提供注册接缝，不内置任何引擎 | 边界最干净，零体积与零依赖 | 不满足「SDK 支持展示图表」的使用预期，宿主必须自己写渲染器 | 低（作为方案 B 的子集保留） |

## 最终决策

- 选择方案：**方案 B**
- 选择原因：
  1. SDK 当前产物 1.1M，引入 2.8M 级引擎不符合第三方嵌入 SDK 的体积预期；方案 B 把引擎留给宿主，SDK 只保留接缝与一个「默认渲染器实现」。
  2. 「注入 → 动态 import → 全局变量 → 降级代码块」四级链路可以覆盖 package ESM、宿主注入、UMD 全局脚本、离线无引擎四类接入场景，且任何一环失败都不影响消息渲染。
  3. 与成熟实现一致：Streamdown 用独立插件包 + peer 依赖，Dify 把引擎装在自己的应用里并懒加载，二者都不把引擎强塞进渲染内核。
- 不选择其他方案的原因：方案 A 的体积/构建冲突见上表；方案 C 无法满足本次需求。
- 安全决策（沿用成熟实现并做增强）：
  - Mermaid 初始化：`startOnLoad: false`、`securityLevel: 'strict'`、`suppressErrorRendering: true`（与 Streamdown、Dify 一致）
  - 源码清洗：按行剔除 `%%{` 开头的 init 指令与 `click ` 开头的交互指令（Dify 做法），并增加源码长度上限与单条消息图表数量上限
  - 注入前用 `DOMPurify` 以 `USE_PROFILES: { svg: true, svgFilters: true }` 二次清洗 Mermaid 产出的 SVG，形成「引擎 strict + 源码清洗 + SVG 再清洗」三层防护
  - 渲染失败只显示本地化提示与源码代码块，不把引擎错误栈写入页面
- 对后续 spec、plan 或人工确认的影响：本次新增 SDK 公开扩展点与依赖策略，属架构边界变化，进入实现前需人工确认；后端、数据模型、API 契约均不变。

## 调研限制

- 已尝试的来源：`https://mermaid.js.org/config/usage.html`、`https://echarts.apache.org/handbook/en/basics/import/`、`https://raw.githubusercontent.com/markdown-it/markdown-it/master/docs/development.md`、`https://raw.githubusercontent.com/cure53/DOMPurify/main/README.md`、`https://docusaurus.io/docs/markdown-features/diagrams` 等官方文档
- 失败原因：执行环境网络受限，`curl` 无法解析域名；申请联网审批被自动审批服务以 403 拒绝（服务侧区域限制），未做绕过
- 采用的替代依据：本机已安装的 `markdown-it@15.0.0`、`mermaid@11.12.3`、`dompurify@3.4.13`、`echarts@5.4.0` 包内源码，以及 Dify、Streamdown、Pi 的源码快照
- 剩余风险与后续补充条件：Mermaid 官方文档的配置项默认值与 `securityLevel` 语义需在联网后复核；本次 spec 中的安全配置项以运行时源码常量和成熟项目实际配置为准。若联网恢复，应在 `verify.md` 中补充官方文档核对记录。

## 剩余风险

- 资料时效性：Mermaid 以 11.12.3 / 11.17.2 两个版本源码为准，未来大版本可能调整配置项；实现中只使用长期稳定的 `initialize` / `render` 与安全字段，并在解析时做能力探测。
- 与本项目上下文的差异：Dify 是自带前端构建的完整应用，本项目 SDK 由第三方页面以 ESM/UMD 两种方式引入，动态 import 与外置依赖行为差异较大，需按「失败即降级」实现。
- 尚未验证的假设：
  1. `vite` lib 模式下将 `mermaid` 置为 external 后，ES 产物保留裸 `import('mermaid')`、UMD 产物走全局变量且不报错，需在实现阶段用构建产物验证。
  2. 流式增量下围栏代码频繁变化时，Mermaid `render()` 失败是可控的（预期大部分为「未闭合语法错误」），需在实现阶段验证降级与重渲染表现。
  3. `DOMPurify` 以 `svg`/`svgFilters` profile 清洗 Mermaid SVG 不会破坏图形结构，需在实现阶段用真实 SVG 验证。
