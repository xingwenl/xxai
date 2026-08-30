# 设计说明：AI SDK 自定义组件（Generative UI）端到端打通

## 目标

- 解决：智能体对话中需要“展示宿主自定义组件”（例如用户信息卡片）。现有 SDK 虽已具备 `registerCustomComponent` 与 `custom` 内容块机制，但后端缺少“业务工具结果 → custom 块”的转换器，且协议字段命名不一致（后端 sanitize 输出 `component_name`，SDK 读取 `componentName`），导致该能力从未真正可用。
- 目标用户：接入 `apps/ai-sdk` 的网页宿主；开发自定义组件的业务开发者。
- 完成后可验证：模型调用业务工具后，消息内容块中出现 `custom` 块，SDK 渲染宿主注册的组件；组件未注册时展示 `fallback`。
- 调研结论引用：依据 `research.md` 的最终决策，采用“工具驱动 + 声明式 custom 块”结合方案（Vercel AI SDK v5 工具驱动范式 + 现有 custom 块作为 JSON 契约雏形）。

## 范围

### 后端 `apps/backend`

- 新增业务工具 `apps/backend/app/modules/tools/business/custom_component.py`：以 `show_user_card` 为示例，返回 `{"kind": "custom", "component_name", "props", "fallback"}`。
- `apps/backend/app/modules/tools/business/registry.py`：导入注册新业务工具。
- `apps/backend/app/modules/conversation/runtime.py`：新增 `custom_content_blocks()` 转换器，并在 `_finish_tool_loop` 的 `GraphResult.content_blocks` 中并入 custom 块（与 `image_content_blocks` 并列）。
- `apps/backend/app/modules/gateway/runtime.py`：`_finish_embed_chat` 收尾链路并入 `custom_content_blocks`。
- `apps/backend/app/modules/conversation/schemas.py`：**不改动**。`sanitize_content_blocks` 保持输出 `component_name`（snake_case），协议字段统一下划线格式，后端不兼容前端。

### SDK `apps/ai-sdk`

- `apps/ai-sdk/src/ui/components/CustomContent.vue`：以 `component_name` 为准读取（前端兼容后端），保留 `componentName` 兜底读取存量数据。
- `apps/ai-sdk/src/core/types.ts`：`MessageContentBlock` 补充 `component_name` 可选字段。
- `apps/ai-sdk/README.md`：新增“自定义组件”开发指南（注册方式、后端工具范式、端到端示例）。

### 测试

- 后端：新增 `custom_content_blocks` 转换器与 `sanitize_content_blocks` 双字段兼容的单元测试。
- SDK：`vue-tsc` 类型检查通过；如已有对应组件测试骨架则补充兼容读取用例。

## 非目标

- 不做完整 A2UI 协议与通用 JSON 渲染器（需维护通用组件库，属独立子项目）。
- 不做 RSC 流式组件（技术栈不匹配）。
- 不做沙箱代码生成（安全与基础设施成本高）。
- 不改数据模型、不改鉴权权限、不改消息事件协议主体结构。
- 不实现“通用 `render_custom_component` 工具”（组件 schema 弱约束，留作后续 request 评估）。

## 风险

- 协议行为变化：`custom` 块协议字段统一为 `component_name`（后端不变，SDK 适配），属 API 契约行为变化，已通过人工确认。
- 回归：存量 `custom` 块（如有）的渲染行为将从“永远 fallback”变为“真正渲染”，属于预期修复；sanitize 新增字段不影响旧客户端读取。
- 联调：Embed WebSocket（`_finish_embed_chat`）与 REST（`_finish_tool_loop`）两条收尾链路都必须并入转换器，遗漏任一处会表现为“工具成功但无卡片”。
- 工具启用：业务工具需在 Agent 的内置工具绑定中启用后模型才会调用（与 `image_generate` 一致），属配置项而非代码缺陷。

## 停点判断

- 是否涉及架构边界变化：否（复用现有业务工具框架与内容块机制）
- 是否涉及数据模型变化：否
- 是否涉及 API 契约变化：是（`custom` 块协议字段统一为 `component_name`，SDK 适配）
- 是否涉及鉴权或权限行为变化：否
- 结论：已通过人工确认（用户 2026-08-30 确认协议统一下划线格式，前端兼容后端），可进入实现。

## 验收标准

1. 后端：`pytest` 新增用例通过，覆盖 `custom_content_blocks` 转换与 `sanitize_content_blocks` 的 `component_name`/`componentName` 双字段输出。
2. 后端：`ruff check` 通过。
3. SDK：`npm run type-check`（`vue-tsc`）通过；`CustomContent.vue` 以 `component_name` 为准渲染，存量 `componentName` 数据可兜底读取。
4. 文档：`apps/ai-sdk/README.md` 新增自定义组件指南，包含组件注册、后端业务工具范式与端到端示例。
5. 端到端（可运行时）：Embed 对话触发 `show_user_card` 后返回 `custom` 块；SDK 对已注册组件渲染卡片，对未注册组件展示 `fallback`。

## 变更记录

### 初始版本

- 时间：2026-08-30
- 变更原因：首次创建 request
- 变更内容：建立“AI SDK 自定义组件端到端打通”初始设计说明
- 影响章节：全部
- 是否触发人工确认：是（API 契约变化）

### 2026-08-30 第 1 次变更

- 变更原因：用户明确协议决策——字段统一使用下划线格式 `component_name`，后端不兼容前端，前端兼容后端
- 变更内容：协议字段统一为 `component_name`；后端 `schemas.py` 不改动，SDK 以 `component_name` 为准读取（保留 `componentName` 兜底）
- 影响章节：范围、风险、停点判断、验收标准
- 是否触发人工确认：是（已获用户确认，2026-08-30）
