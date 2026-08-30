# 业界调研记录：AI SDK 自定义组件（Generative UI）端到端打通

## 调研问题

- 如何让 AI Agent 在对话中“展示”宿主网页的自定义组件（例如用户信息卡片），而不是只能输出 Markdown 文本？
- 在“模型 → 后端 → SDK 渲染”链路上，业界有哪些成熟做法？各自的适用条件、收益和限制是什么？
- 本次实现应选择哪种方案，边界划在哪里？

## 功能复杂度

- 级别：核心功能
- 选择理由：本次改动横跨后端消息协议、业务工具框架和 SDK 渲染层，且涉及 `custom` 内容块协议字段的兼容行为（`component_name` / `componentName`），属于跨服务联动修改。
- 最低调研要求：至少包含官方文档来源与成熟开源项目，并完成方案比较。

## 参考依据

### 来源 1：Vercel AI SDK v5 工具调用驱动 UI（官方文档）

- 类型：官方文档
- 名称：AI SDK Chatbot Tool Usage
- 链接：https://ai-sdk.dev/docs/ai-sdk-ui/chatbot-tool-usage
- 版本或发布日期：2025 年（v5 起为当前主线）
- 调研日期：2026-08-30
- 核心做法：模型调用工具后，`useChat` 把工具调用与结果拆成 `tool-<name>` 的 parts，前端针对每个工具名渲染对应组件；工具声明的 `input_schema` 就是组件 props 的契约来源。
- 对本项目的启发：工具调用是“模型决定渲染什么组件”最可靠的触发方式；props 由工具 schema 约束，可靠性高；渲染层按组件名分发即可。本项目已有 `@business_tool` 工具框架和 `registerCustomComponent` 注册表，天然契合该范式。

### 来源 2：Google A2UI（Agent-to-User UI，声明式 JSON 组件契约）

- 类型：官方规范草案 + 社区深度解析
- 名称：What is A2UI / A2UI 协议深度解析
- 链接：https://agent-ready.dev/what-is-a2ui 、https://www.cnblogs.com/itech/p/21609276
- 版本或发布日期：2025 年发布草案
- 调研日期：2026-08-30
- 核心做法：把“页面/卡片”描述成与模型无关的 JSON 块级 schema（组件 + props），由 agent 端渲染器消费 JSON 生成 UI。
- 对本项目的启发：仓库现有 `custom` 内容块（`component_name` + `props` + `fallback`）本质上就是简化版的 JSON 组件契约，方向正确，无需推倒重来。

### 来源 3：A2UI、AG-UI 与 Vercel AI SDK 的对比分析

- 类型：生产实践/技术文章
- 名称：A2UI vs AG-UI vs Vercel Agent UI 对比
- 链接：https://qubittool.com/zh/blog/a2ui-vs-ag-ui-vercel-agent-ui-comparison
- 版本或发布日期：2025 年
- 调研日期：2026-08-30
- 核心做法：对比三类协议：纯 UI 渲染协议（A2UI）、纯通信协议（AG-UI）与 SDK 绑定方案（Vercel AI SDK）。
- 对本项目的启发：本项目选择“SDK 绑定 + 简化 JSON 契约”的组合，即用后端业务工具保证数据契约，用 `custom` 块承载渲染指令，两者职责清晰。

### 来源 4：声明式卡片生态（Adaptive Cards / Slack Block Kit）

- 类型：成熟开源项目 / 生产实践
- 名称：Adaptive Cards、Slack Block Kit
- 链接：https://adaptivecards.io/ 、https://api.slack.com/block-kit
- 版本或发布日期：长期维护
- 调研日期：2026-08-30
- 核心做法：用受限的声明式 schema（Card/Block JSON）表达信息展示类 UI，渲染器负责落地，服务端只产出 JSON。
- 对本项目的启发：信息卡片类组件适合声明式契约；但通用渲染器需要维护一整套组件库，超出本次范围，可作为长期演进方向。

### 来源 5：RSC 流式组件与沙箱代码生成（不采用方案的依据）

- 类型：官方文档 / 生产实践
- 名称：Vercel streamUI（ai-sdk-rsc）、Claude Artifacts、ChatGPT Canvas
- 链接：https://ai-sdk.dev/docs/ai-sdk-rsc/streaming-ui
- 版本或发布日期：2023–2025；Vercel 已转向 AI Elements + JSON-Render 方向
- 调研日期：2026-08-30
- 核心做法：streamUI 通过 React Server Components 流式渲染组件；Artifacts/Canvas 在沙箱中执行模型生成的代码来产出 UI。
- 对本项目的启发：RSC 仅适用于 React Server Components，与本项目 Vue 3 SDK 不匹配，且官方已转向 JSON 渲染方向；沙箱代码生成安全与基础设施成本高，两者均不采用。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| A. 工具调用驱动 + 组件注册表（Vercel AI SDK v5 范式） | 模型触发可靠；props 有 schema 约束；与现有 `@business_tool` 框架、`registerCustomComponent` 完全一致 | 每个组件需要一个后端业务工具（声明式薄文件）；工具需在 Agent 绑定中启用 | 高 |
| B. 通用声明式 JSON 契约（A2UI / Open-JSON-UI / Adaptive Cards） | 与模型和 SDK 解耦；一次实现多处复用；卡片类 UI 主流 | 通用渲染器需维护整套组件库；复杂交互表达能力有限 | 中，`custom` 块已具备雏形 |
| C. RSC 流式组件（Vercel streamUI） | 组件流式渐进渲染；类型安全 | 仅限 React Server Components；官方已转向 AI Elements；与 Vue 3 SDK 不匹配 | 低 |
| D. 沙箱代码生成（Claude Artifacts / ChatGPT Canvas） | 表达力最强，任意 UI 可生成 | 任意代码执行的安全成本高；沙箱基础设施重 | 低 |

## 最终决策

- 选择方案：方案 A（工具驱动）为主，复用仓库现有 `custom` 块机制（方案 B 的雏形）作为承载协议。
- 选择原因：模型调用专用业务工具（如 `show_user_card`）→ 工具返回 `{"kind": "custom", "component_name", "props", "fallback"}` → 后端新增 `custom_content_blocks()` 转换器并入消息内容块 → sanitize 校验后下发 → SDK 按 `registerCustomComponent` 注册表渲染，未注册时展示 `fallback`。该链路与现有 `image_generate` 业务工具 + 图片内容块的成熟范式完全一致，改动面最小。
- 不选择方案 B 作为主方案的原因：完整 JSON 渲染器需要维护通用组件库并定义渲染协议，属于新的独立子项目；本次以“端到端打通 + 沉淀新增组件范式”为目标，`custom` 块已覆盖渲染指令承载。
- 不选择方案 C、D 的原因：技术栈不匹配（React RSC）或安全/成本过高，且 Vercel 官方已转向 JSON 渲染方向，RSC 方案趋于停更。
- 对后续 spec、plan 或人工确认的影响：`custom` 块协议字段统一为 snake_case `component_name`（后端保持输出不变，SDK 兼容读取）；该协议字段行为变化已在实现前经用户确认（2026-08-30）。

## 剩余风险

- 资料时效性：AI SDK v5、A2UI 均为 2025 年新产物，方案演进较快；本决策基于 2026-08-30 可获得的资料。
- 与本项目上下文的差异：Vercel AI SDK 是 React 生态，本项目 SDK 为 Vue 3；已通过复用仓库现有注册表与内容块机制规避技术栈差异。
- 尚未验证的假设：`custom` 块在 Embed WebSocket 与 REST 两条收尾链路中都能正确下发；宿主组件可用性由宿主保证，SDK 只负责分发，`fallback` 兜底。
