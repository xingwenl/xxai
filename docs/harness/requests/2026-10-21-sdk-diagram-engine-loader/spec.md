---
id: 2026-10-21-sdk-diagram-engine-loader
tier: B
risk: medium
approval:
  required: true
  granted: false
  why: ["跨 apps/ 改动：apps/ai-sdk 公开配置 API + apps/desktop 宿主", "configureMarkdownDiagrams 入参类型扩展（SDK 公开 API 契约变化，向后兼容）"]
---

## 目标与范围

一句话：把图表引擎的**加载策略**（懒加载时机、并发去重、失败可重试、模块命名空间兜底）从宿主收进 ai-sdk——`configureMarkdownDiagrams` 除接收引擎实例外，再接收 `() => import('mermaid')` 这类 loader；`apps/desktop/front` 里那段加载时序逻辑缩成一次注册调用；同时修掉 README §10.1 与实现矛盾的「方式一：npm install 打包器会自动解析动态 import」。

背景（上一轮已完成并实测）：desktop/front 装了 echarts 却不出图，根因是 SDK 第三档解析在浏览器执行 `import(变量)` 必然失败；宿主改用字面量 import + `configureMarkdownDiagrams` 显式注入后，构建产物切出独立 chunk、运行时真实拉取并注入。但「何时加载、被多少图表并发调用、失败后要不要重试」这套策略写在了宿主，每个接入方都要复制一遍，且首条带图消息可能抢在注入完成前渲染成代码块（SDK 的降级不自动重试）。

**不做**：不改渲染器安全策略（mermaid 严格级别/源码清洗/DOMPurify、echarts 只收 JSON）、不改降级语义与提示文案、不改事件协议与后端、不做 CDN 自动发现、不抽共享包、不动冻结的存量 request `2026-09-17-ai-sdk-markdown-diagrams`、不修 `scripts/verify-package.mjs` 对 `import("mermaid")` 字面量的历史断言（CHANGELOG 2026-10-19 已记录为预存在失败）。

## 来源与方案比较

现状依据（本仓库源码与实测）：
- 解析三级：`apps/ai-sdk/src/ui/markdown/index.ts:54` 的 `configureMarkdownDiagrams`；说明符刻意可变 + `/* @vite-ignore */`，理由见 `apps/ai-sdk/src/ui/markdown/optional-engines.ts:1-17`；两个解析函数在 `echarts-renderer.ts:119-139`、`mermaid-renderer.ts:103-123`。
- 实测 1：headless Chrome 执行变量 `import('echarts')` → `TypeError: Failed to resolve module specifier 'echarts'`，被 `.catch(() => null)` 吞掉后围栏降级为代码块。
- 实测 2：宿主用字面量 import 显式注入后，构建产出 `assets/echarts-*.js`（1,124.20 kB）并被运行时真实请求。
- 宿主当前实现（本次要删）：`apps/desktop/front/src/lib/assistant.ts:21-41` 加载函数、`:88-90` 启动、`:126-127` `await` 后再建 client。

官方依据（2026-10-21 访问）：
- Vite 5「Dynamic Import」：`import()` 只有**字面量**能在构建期被处理，变量/拼接必须显式用 `import.meta.glob`，否则构建期无法解析——https://vitejs.dev/guide/features#dynamic-import
- Rollup 的 `output.dynamicImportInCjs`/动态导入语义同理：无法静态求值的动态导入原样保留——https://rollupjs.org/configuration-options/
- 结论：引擎的**取包**（字面量 import）只能发生在宿主打包器里；SDK 能接管的是**加载策略**，这正是本次要收进 SDK 的部分。

方案比较：

| 方案 | 做法 | 结论 |
|---|---|---|
| A 现状：宿主注入实例 + 宿主管时序 | 宿主自行 import 后 `configureMarkdownDiagrams({ echarts })` | 能用，但时机/并发/重试/命名空间兜底每个宿主各写一遍；首图可能抢跑 |
| B loader 注入（采纳） | `configureMarkdownDiagrams({ echarts: () => import('echarts') })`，SDK 在首次 mount 时 `await` loader、单飞去重、失败清缓存可重试 | 宿主 1 行；策略集中；loader 不被调用就不拉包，保持「可选依赖」 |
| C 全局脚本 + `window.echarts` | index.html 引 CDN | 桌面离线/本地化部署不可用，版本不可控 |
| D SDK 内置引擎 | 把 3.8MB 打进核心包 | 所有宿主背重量，违背可选引擎设计 |

## 被否决的选项

- **保持宿主注入实例（方案 A）**：加载时序与重试策略散落在每个宿主，新宿主照抄才不出 bug；且「先建连后注入」会让首条带图消息降级成代码块。
- **SDK 内置引擎、或在 dist 里写字面量 import**：打包器不会改写预构建 dist 里的动态导入（实测浏览器 TypeError），内联则违背可选依赖，两个极端都不可行。
- **全局 script + `window.echarts`**：桌面应用离线与内网部署不可靠，版本与 CSP 都不可控。
- **新建 `@repo/markdown-engines` 共享包**：只是把同一行字面量换个位置，当前只有一个宿主，净收益为零却多一个发布单元。
- **由 SDK 侧用 `import.meta.glob` 生成加载器**：glob 只能写在宿主工程源码里，SDK 无法跨包 glob，方案不成立。

## 停点判断

- 是否涉及架构边界变化：否（沿用既有 `configureMarkdownDiagrams` 接缝，只扩展入参）
- 是否涉及数据模型变化：否
- 是否涉及 API 契约变化：是（SDK 公开类型 `MarkdownDiagramOptions.mermaid/echarts` 扩展为「实例 | null | loader」，向后兼容）
- 是否涉及鉴权或权限行为变化：否
- 结论：命中「跨 apps/ 改动」与「公开 API 契约变化」，`approval.required: true`；本文件写完后先确认要点，再写实现代码。

## 变更点

- `apps/ai-sdk/src/ui/markdown/mermaid-renderer.ts`：新增 `MermaidEngineLoader`/`MermaidEngineInput` 类型；`setMermaidEngine` 接受 loader；`resolveMermaid` 注入分支 await loader（单飞 promise、`default ?? namespace` 兜底、返回非引擎对象视为失败、失败后清空缓存以允许重试）。
- `apps/ai-sdk/src/ui/markdown/echarts-renderer.ts`：同上（`EChartsEngineLoader`/`EChartsEngineInput`，按 `init` 是否为函数做运行时窄化）。
- `apps/ai-sdk/src/ui/markdown/index.ts`：`MarkdownDiagramOptions.mermaid/echarts` 改用新 union 并导出新类型；补充注释说明「loader 在首个围栏挂载时才会被调用」。
- `apps/ai-sdk/src/ui/__tests__/markdown-diagram-renderers.test.ts`：新增 loader 用例——未挂载围栏前不调用 loader；并发多个 mount 只调用一次（单飞）；loader 失败时降级且下次可重试；返回模块命名空间时走 `default` 兜底；实例注入优先于 loader；`null` 仍表示禁用。
- `apps/desktop/front/src/lib/assistant.ts`：删除 `diagramEnginesReady`/`loadDiagramEngines`/启动与 `await` 时序（:21-41、:88-90、:126-127），改为模块加载时一次 `configureMarkdownDiagrams({ mermaid: () => import('mermaid'), echarts: () => import('echarts') })`；保留一段注释解释「为什么字面量 import 必须在宿主侧」。
- `apps/ai-sdk/README.md` §10.1：删掉「方式一：npm install，打包器会自动解析动态 import」，改为「安装 + loader 注入（推荐）」；保留全局脚本与实例注入两种方式并各自写明适用条件；§10.4 排查表把「动态 import 失败」一行对齐新写法。
- `apps/desktop/front/package.json` + `pnpm-lock.yaml`：补提交 echarts ^6.1.0 / mermaid ^12.0.0（当前在工作区未提交，HEAD 单独 checkout 会因 import 未声明包而构建失败）。
- `docs/CHANGELOG.md`：新增 2026-10-21 条目。
- 新增 `tools/harness/verify/2026-10-21-sdk-diagram-engine-loader.sh` 与运行产出的 `verify.md`。

## 验收标准

1. `pnpm --filter xxai-agent run type-check` 通过。
2. `pnpm --filter xxai-agent exec vitest run` 通过，且新增用例覆盖：懒加载、单飞、失败可重试、`default` 兜底、实例优先、`null` 禁用。
3. `pnpm --filter xxai-agent run build` 成功；`dist/xxai-agent.es.js` 未内联 mermaid/echarts 代码，动态导入仍以变量形式保留。
4. `pnpm --filter desktop-front exec tsc --noEmit` 与 `pnpm --filter desktop-front build` 通过；构建产物中主 chunk 不含 `loadDiagramEngines`、含带两个 loader 的 `configureMarkdownDiagrams` 调用，且存在独立的 `echarts-*.js` / mermaid chunk。
5. headless Chrome 加载 desktop 构建产物（stub `/api/desktop/agent-config` 返回 `enabled:true`）：加载完成后 8 秒内不出现 echarts/mermaid chunk 请求（懒加载生效），页面无未捕获 `TypeError`。
6. `apps/ai-sdk/README.md` §10.1 不再出现「npm install 就会自动解析动态 import」的说法，含 loader 示例与「字面量 import 才能切 chunk」的限制说明。
7. `python3 tools/harness/audit.py` 无本次新增 ERROR。

未执行项（预期）：真实 AI Base + 真实模型消息下「图表真的画出来」的端到端（依赖本机后端/模型可用），验证脚本需显式列出。
