# 实施计划

## 变更文件

- `apps/ai-sdk/package.json`、`package-lock.json`：增加并锁定语义解析依赖，记录包体积影响。
- `apps/ai-sdk/src/core/page/types.ts`：定义页面快照、元素引用、动作参数和稳定错误码。
- `apps/ai-sdk/src/core/page/visibility.ts`：实现顶层文档当前视口的可见性、遮挡和可操作判断。
- `apps/ai-sdk/src/core/page/snapshot.ts`：基于 DOM、ARIA accessible name 和 tabbable 结果生成限长快照。
- `apps/ai-sdk/src/core/page/ref-store.ts`：保存当前快照版本和临时 `ref`，在 DOM/URL 变化后失效。
- `apps/ai-sdk/src/core/page/actions.ts`：实现点击、输入、滚动、等待和提取；执行前重新校验引用。
- `apps/ai-sdk/src/core/page/tools.ts`：把页面能力封装为六个内置 `ToolDefinition`，与现有 `ToolRegistry` 合并并避免名称冲突。
- `apps/ai-sdk/src/core/client.ts`、`tool-registry.ts`：增加内置工具生命周期、页面重置和清理，不改变业务方 `registerTool()` 语义。
- `apps/ai-sdk/src/core/__tests__/page/*.test.ts`：覆盖快照、引用失效、可见性、风险分类和动作错误。
- `apps/ai-sdk/src/core/__tests__/client.test.ts`、`protocol.test.ts`：覆盖内置工具注册、调用、确认、重复 callId 和重连。
- `apps/ai-sdk/README.md`：补充自动页面工具的接入开关、限制、风险确认和示例。
- `docs/harness/requests/2026-08-07-page-interaction-tools/verify.md`、`acceptance.md`：记录真实验证证据和验收结论。

## 实施步骤

### 1. 锁定依赖和公共类型

- 先检查 `dom-accessibility-api`、`aria-query`、`tabbable` 的现代浏览器兼容性、许可证和构建体积。
- 仅在确有必要时引入依赖；优先复用原生 `Element.matches()`、`getBoundingClientRect()`、`document.elementFromPoint()`。
- 定义 `PageSnapshot`、`PageElement`、`PageActionContext` 和错误码，明确 16 KiB 文本、200 元素、512 字符字段限制。

### 2. 实现快照构建和引用生命周期

- 遍历当前顶层 `document.body`，过滤 `display:none`、`visibility:hidden`、零尺寸、视口外、disabled 和不可交互节点。
- 使用 accessible name、ARIA role、原生控件类型和 tabbable 结果确定 role/name/value/status。
- 文本按可见文本块聚合，过滤脚本、样式、隐藏属性和明显重复内容；URL 只保留 origin + path。
- 每次快照生成新的 `snapshotId`，元素引用只在该快照及同一页面版本内有效。
- 监听页面 `click`、`input`、`change`、`scroll`、`popstate` 和 `hashchange`，必要时将引用标记为可能过期；动作时仍以实时校验为准。

### 3. 实现页面动作适配器

- `page_click` 只接受 `snapshotId/ref`，重新定位并检查角色、名称、可见性、禁用状态和遮挡后触发标准 `click()`。
- `page_type` 只接受 text/search/email/tel/url/number 和 `[contenteditable]`；实现 replace/append，拒绝 password/file 与跨域上下文。
- `page_scroll` 限制方向和最大距离，执行后返回滚动位置和“需要重新快照”的结果。
- `page_wait` 只等待有限的 DOM/文本条件，不执行模型提供的脚本；超时返回稳定错误。
- `page_extract` 仅从当前快照提取已暴露的文本和值，禁止重新读取整页 HTML。

### 4. 接入现有工具运行时和确认链路

- 内置工具使用保留前缀 `page_`，由 SDK 在连接建立前注册；业务方同名工具不覆盖内置工具，冲突记录为本地错误。
- 保持服务端三重授权交集和现有 `host_tool_call` 协议；后端不因自动发现扩大白名单。
- 根据元素语义、操作类型和可配置关键词计算 `sideEffect`/`requiresConfirmation`；服务端要求确认时优先于本地推断。
- 复用现有 `resolveToolCall()`、确认 UI、超时和结果大小限制；断线不重试点击、输入等副作用动作。

### 5. 测试和文档

- 使用 jsdom/真实浏览器 fixture 覆盖普通按钮、链接、输入框、checkbox、select、动态 DOM、虚拟列表和遮挡。
- 覆盖密码/文件输入、跨域 iframe、任意 selector/脚本注入、过期 ref、重复 callId、确认拒绝和动作超时。
- 执行 SDK typecheck、Vitest、build，并分别在 Chrome、Edge、Safari、Firefox 做最小集成回归。
- 更新 `README.md` 和 runbook，说明自动页面工具不是任意 DOM/脚本执行器，以及高风险确认行为。

## 测试步骤

- `cd apps/ai-sdk && npm install`：依赖锁文件无非预期漂移。
- `cd apps/ai-sdk && npm run type-check`：类型检查通过。
- `cd apps/ai-sdk && npm run test -- --run`：页面模块、协议和客户端测试通过。
- `cd apps/ai-sdk && npm run build`：构建成功，产物可导入且包体积增量已记录。
- `cd apps/ai-sdk && npm run verify-package`：发布包包含页面工具所需代码且不包含测试文件。
- 真实浏览器 fixture：四种现代浏览器各执行快照、点击、输入、动态更新和高风险确认场景。

## 回滚说明

- 实现提交可整体回滚；若依赖已发布，先发布不注册 `page_` 工具的兼容版本，再移除依赖。
- 保持既有业务宿主工具和 WebSocket 事件不变；页面工具关闭时 SDK 应继续支持 `registerTool()`。
- 不删除任何后端审计数据；仅停止自动发现工具注册和调用。

## 人工确认点

- 已确认：2026-08-08，用户确认页面自动发现方案、当前视口范围、现代浏览器范围和分级确认策略。
- 实现前仍需确认：最终依赖版本及许可、`page_` 工具是否默认启用、关键词/区域配置的公开 API。
- 实现中不得扩大为任意脚本执行、任意 URL 导航、跨域 iframe 或副作用自动重试。
