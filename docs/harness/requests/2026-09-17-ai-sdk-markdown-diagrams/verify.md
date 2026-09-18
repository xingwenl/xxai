# 验证记录

## 执行命令

以下命令均在 2026-09-17 实际执行，工作目录为 `apps/ai-sdk`（除最后两条）。

1. `npm run type-check`
2. `npx vitest run`
3. `npm run build`
4. `npm run verify-package`
5. `node /tmp/dist-smoke.mjs`（临时脚本：用本机 jsdom 加载 `dist/xxai-agent.es.js` 真实产物做 DOM 冒烟）
6. `cd <仓库根> && python3 tools/harness/audit.py`

## 预期结果

1. `vue-tsc` 无类型错误。
2. 全部用例通过，且新增用例覆盖围栏注册表、渲染器纯逻辑、Markdown 管线与浏览器路径。
3. 构建成功；`dist` 中不内联图表引擎；产物体积相比改动前（`dist` 约 1.1M，主包约 437K）无明显增长。
4. 产物校验通过，并校验 `configureMarkdownDiagrams` / `registerMarkdownFenceRenderer` 的 CJS 导出与引擎外置。
5. 真实产物在 DOM 环境下能渲染 mermaid / echarts / 自定义语言围栏，并在引擎不可用时降级为代码块。
6. 无本次新增 ERROR。

## 实际结果

1. **通过**：`vue-tsc --noEmit` 无输出错误。
2. **通过**：`Test Files 19 passed (19) / Tests 131 passed (131)`。新增用例分布：
   - `src/ui/__tests__/markdown-fence-registry.test.ts`（5）：注册、覆盖、语言归一化、忽略非法输入、内置语言默认注册。
   - `src/ui/__tests__/markdown-content.test.ts`（7）：未注册语言保持代码块、内置语言输出占位节点、源码不进 DOM、自定义语言与 id 顺序、语言大小写与附加信息、重复渲染不残留、源码脚本不进 HTML。
   - `src/ui/__tests__/markdown-diagram-renderers.test.ts`（14）：Mermaid 指令清洗、就绪判断、严格安全级别初始化、清洗后源码传给引擎、缓存命中与主题切换、源码未就绪不调引擎、引擎缺失返回 null、显式禁用、渲染异常上抛；ECharts 仅接受 JSON 对象、深色主题透传、卸载释放实例、非法配置与引擎缺失拒绝渲染。
   - `src/ui/__tests__/markdown-diagram-dom.test.ts`（6，jsdom 环境）：SVG 水合且脚本被清洗、源码不进页面文本、未注册语言保持代码块、引擎缺失降级并给出提示、自定义渲染器挂载与卸载清理、文本更新后重新渲染并释放旧实例。
3. **通过**：构建成功，`dist/xxai-agent.es.js` 437.75 kB（gzip 135.75 kB）、`dist/xxai-agent.umd.cjs` 298.07 kB（gzip 112.37 kB）、`dist/style.css` 34.70 kB；`dist` 目录总体积仍为约 1.1M，与改动前一致。产物内保留 `import("mermaid")`、`import("echarts")`，未内联引擎。
4. **通过**：`Package entries verified: ./dist/xxai-agent.es.js, ./dist/xxai-agent.umd.cjs, ./dist/index.d.ts, ./dist/style.css`。
5. **通过**：`DIST_SMOKE:{"exports":true,"mermaidSvgRendered":true,"mermaidSourceReceived":true,"echartsRendered":true,"echartsInitTheme":"light","customLanguageRendered":true,"pythonCodeBlock":true,"sourceNotInPageText":true,"fallbackCodeBlock":true,"fallbackHint":true,"fallbackNoSvg":true}`。
6. **通过**：`requests: 55  ERROR: 1  WARN: 18`，唯一 ERROR 为既有 request `2026-08-04-skill-zip-import`（`status` 非法值 `completed`），与本次改动无关；本次 request 无新增 ERROR/WARN。

### 实现过程中发现并修复的缺陷

首版水合逻辑只监听清洗后的 HTML 字符串，导致「HTML 不变但图表源码变化」时（例如流式输出只更新围栏内容）不会重绘。已在 `MarkdownContent.vue` 中改为监听渲染结果对象，并按占位节点复用已挂载组件，`markdown-diagram-dom.test.ts` 的「文本更新后重新水合」用例覆盖该场景。

### 2026-09-17 第 2 次验证（fix）

- `npx vitest run` → `Test Files 19 passed (19) / Tests 136 passed (136)`（新增 5 个用例：engine-missing / source-not-ready 原因码、解析失败后可重试、宽松 JSON 归一化、UI 层降级原因文案）。
- `npm run build` → `dist/xxai-agent.es.js` 423.80 kB（gzip 130.54 kB）、`dist/xxai-agent.umd.cjs` 287.12 kB（gzip 107.73 kB）。
- `npm run verify-package` → 通过。
- `node /tmp/dist-smoke.mjs`（真实产物 + jsdom）→ `DIST_SMOKE` 全部为 true，含 `fallbackHint:true`。
- `npm run type-check` → 本次改动无类型错误；唯一报错来自既有测试 `src/ui/__tests__/chat-message.ssr.test.ts`，原因是本地 `node_modules` 变成 npm 与 pnpm 混合布局（`node_modules/@vue/runtime-core@3.5.40` 与 `node_modules/.pnpm/@vue+runtime-core@3.5.43` 两份类型），与本次改动无关，需重装依赖消除。
- 单测新增了 `vi.mock('mermaid' | 'echarts')`，保证「运行时加载失败」这条路径在本机已安装引擎的情况下也能确定性复现。

## 失败项与例外

- **未执行 headless Chrome 浏览器验证**：沙箱内 `Google Chrome --headless=new` 以 `exit=134`（SIGABRT）退出；申请沙箱外执行时自动审批服务返回 403（服务侧区域限制），未做任何绕过。替代方案为 jsdom 环境下的 DOM 冒烟（源码级 + 真实产物级），已覆盖同样的断言点。
- **未用真实 mermaid / echarts 引擎渲染**：本机未安装这两个包且无法联网安装，验证使用注入的假引擎，覆盖装配、生命周期、清洗与降级路径，不覆盖引擎自身的渲染正确性。
- **`package-lock.json` 未同步 `jsdom`**：`apps/ai-sdk/package.json` 新增 `devDependencies.jsdom`，本地运行通过符号链接使用本机已有的 `jsdom@26.1.0`，锁文件需联网执行 `npm install` 后生成。
- **未执行后端/前端回归**：本次未改动后端、`apps/front`、消息协议与数据模型，无需回归。
