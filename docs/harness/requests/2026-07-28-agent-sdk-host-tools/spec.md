# Phase 2B 宿主页面工具设计说明

## 目标

在 Phase 2A 的 `ai-agent.v1` WebSocket 和 `apps/ai-sdk` 基础上，提供受后台策略约束的宿主页面工具调用。平台管理员可以配置工具 Schema、Agent 白名单和 Client/token 白名单；第三方页面注册真实函数；Agent 只能请求三重白名单交集内的工具；最终用户对有副作用操作进行确认；后端保存完整调用状态和独立审计事实。

关键方案来自本 request 的 `research.md`：后端负责授权、状态机、幂等和审计，SDK 负责对已授权工具做本地 Schema 校验和函数执行，不执行任意脚本或任意 DOM 操作。

## 范围

### 后端数据模型

新增以下独立模型及 Alembic 迁移：

- `HostToolPolicy`：平台级工具名称、描述、输入/输出 JSON Schema、`side_effect`、确认策略和启用状态。
- `AgentHostTool`：Agent 与宿主工具策略的绑定及启用状态。
- `EmbedClientHostTool`：Embed Client 允许放入 token claim 的工具名称白名单。
- `HostToolCallAudit`：以 `call_id` 唯一标识一次调用，保存平台、Agent、平台最终用户、Conversation、请求、工具、参数摘要、脱敏参数、状态、确认时间、结果摘要和错误。

调用状态严格限制为：`requested`、`awaiting_confirmation`、`running`、`succeeded`、`failed`、`rejected`、`expired`。状态迁移使用条件更新，保证重复确认、重复结果和重连不会重复执行。

### 管理 API

在现有后台 JWT 与平台管理员依赖下新增：

- `POST /api/v1/platforms/{platform_id}/host-tools`：创建工具策略。
- `GET /api/v1/platforms/{platform_id}/host-tools`：分页/限制查询工具策略。
- `PATCH /api/v1/platforms/{platform_id}/host-tools/{tool_id}`：更新 Schema、描述、副作用、确认策略和启用状态；Schema 变化默认撤销启用状态，避免旧页面实现误执行。
- `PUT/DELETE /api/v1/platforms/{platform_id}/agents/{agent_id}/host-tools/{tool_id}`：绑定或解除 Agent 工具策略。
- `PUT/DELETE /api/v1/platforms/{platform_id}/embed-clients/{client_id}/host-tools/{tool_id}`：控制工具是否可进入该 Client 签发的 token。
- `GET /api/v1/platforms/{platform_id}/host-tool-audits`：查询独立宿主工具审计，不返回未脱敏参数。

扩展 `POST /api/v1/embed/tokens` 请求，增加可选 `host_tool_names`。服务端只把请求名称与 Client 白名单求交后写入 token claim `host_tools`，不信任浏览器连接阶段提交的工具名称。

### WebSocket 协议

扩展现有协议事件：

- 客户端 `host_tools_register`：提交当前页面工具名称、描述和 JSON Schema；只接受 token 允许、Agent 策略允许且名称/Schema 与后台策略一致的工具。
- 服务端 `host_tool_call`：发送 `callId`、工具名、经过 Schema 校验的参数、`sideEffect` 和确认要求。
- 服务端 `confirmation_required`：发送 `callId`、确认文本、工具名和脱敏参数摘要。
- 客户端 `confirmation_resolve`：提交 `callId` 与 `approved`，服务端按主体和当前连接重新授权。
- 客户端 `host_tool_result` / `host_tool_error`：提交 `callId`、结果或稳定错误；只允许当前连接对应的 pending 调用回传。

单个 WebSocket 连接最多一个进行中的宿主调用；工具结果默认不超过 32 KiB，协议消息不超过 64 KiB。所有事件都带 `requestId` 或 `callId`，并沿用 2A 的 sequence、重放和错误 envelope。

### SDK

- `ToolRegistry` 注册时验证名称、Schema、函数和超时配置，并发送 `host_tools_register`；未获 `session_ready` 或注册确认前不执行调用。
- 收到 `host_tool_call` 时只查找本地已注册函数，再用 Draft 2020-12 校验参数；未知工具、Schema 不一致、超时或 AbortSignal 触发均回传 `host_tool_error`。
- `confirmation_required` 通过客户端回调和事件发给宿主页面；默认不自动批准有副作用调用。调用方调用 `resolveToolCall(callId, approved)` 后才回传 `confirmation_resolve`。
- 成功结果经过大小限制和递归敏感字段过滤后回传；结果回传失败不触发自动重试。
- `destroy()` 清除工具调用、确认和超时句柄，不保留 token、参数或结果到 localStorage、URL、日志或错误对象。

## 非目标

- 不执行任意 JavaScript、`eval`、脚本字符串、未注册函数、任意 DOM 操作或任意 URL 导航。
- 不把宿主工具并入 MCP 表、MCP 确认流程或 MCP 审计查询。
- 不增加管理后台页面；本 request 只提供管理 API。
- 不实现跨标签页协调、配额、指标、CDN/UMD 发布或 React 包。
- 不在断线后自动重试 `write`、`financial`、`external` 或 `navigation` 工具。

## 风险

- 数据模型与公开 WebSocket/API 契约变化会影响迁移、OpenAPI 和 SDK 兼容性。
- 页面函数本身仍由接入方实现，后台不能替代页面业务授权、CSRF 防护和副作用回滚。
- 工具执行完成但回传丢失时只能依据 `callId` 查询已有状态，不能通过重复执行恢复。
- Schema 或策略变更后旧 token 可能在 TTL 内存在，服务端在注册、调用和结果阶段都要重新检查主体与当前策略。
- 参数和结果脱敏规则不可能识别所有业务秘密，默认按敏感字段名递归过滤，并限制原始内容进入日志。

## 停点判断

- 架构边界变化：是，新增宿主工具协调器并扩展 WebSocket 网关职责。
- 数据模型变化：是，新增策略、绑定和独立调用审计表。
- API 契约变化：是，新增管理 API、token claim 和 WebSocket 事件。
- 鉴权或权限行为变化：是，新增 Client/Agent/token/页面注册三重授权。
- 人工确认：已于 2026-07-28 获得确认，授权范围为本文件的推荐方案；实现必须保持上述四项约束。

## 验收标准

### 授权与隔离

- 未同时满足 Client token claim、Agent 发布策略和当前页面注册的工具永远不能收到 `host_tool_call` 或执行。
- 平台、Agent、最终用户和 Conversation 不匹配时，注册、确认和结果回传均返回稳定权限错误。
- 浏览器提交的工具描述、平台 ID、Agent ID 和用户 ID 不能扩大 token 或后台策略权限。

### 状态与副作用

- 每个 `callId` 只产生一条宿主调用审计记录；重复确认和重复结果不重复调用页面函数。
- `none` 工具可以自动执行；其余副作用类型未经确认不执行，拒绝和超时进入终态。
- 工具执行超时、AbortSignal、参数无效、结果过大和函数异常分别产生可查询失败状态。
- 断线不重试副作用调用；调用方可按 `callId` 获得最终状态。

### SDK 与协议

- `host_tools_register`、`host_tool_call`、`confirmation_required`、`confirmation_resolve`、`host_tool_result`、`host_tool_error` 均有协议解析和定向测试。
- 后端与 SDK 都使用 JSON Schema Draft 2020-12 校验参数，SDK 不执行未注册名称。
- `destroy()` 后无 WebSocket、计时器、事件监听和待执行工具残留。

### 工程验证

- 后端迁移、模型、服务、权限、状态机和 WebSocket 测试通过；SDK type-check、Vitest、build 通过。
- 测试覆盖至少包括跨平台拒绝、三重白名单、确认竞态、重复 callId、重复结果、超时、结果大小限制和断线场景。
- `verify.md` 记录真实命令、输出、失败项和未覆盖风险；`acceptance.md` 对每条验收标准给出结论。

## 变更记录

### 2026-07-28 初始版本

- 变更原因：Phase 2A 已验收，开始独立 Phase 2B 宿主页面工具 request。
- 变更内容：建立后台策略、Client/token 白名单、SDK 执行、确认、状态机和独立审计边界。
- 影响章节：全部。
- 是否触发人工确认：是，用户已于 2026-07-28 确认推荐方案并授权进入实现。
