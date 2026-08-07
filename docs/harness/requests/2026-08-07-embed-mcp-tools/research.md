# Embed 对话接入 MCP 工具调研记录

## 调研问题

本次需要让 `apps/ai-sdk` 发起的 Embed WebSocket 对话使用 Agent 已绑定的 MCP 工具，并为有副作用的 MCP 调用提供 SDK 内置确认界面。调研重点是：

- 如何同时向模型暴露 MCP、Skill 和浏览器宿主工具，又不混淆执行位置与凭据边界；
- 如何让确认、拒绝和超时后仍能恢复同一次模型工具循环；
- 如何在后台用户与 Embed 最终用户之间保持 MCP 审计主体准确；
- 如何保持现有 REST 对话、MCP 管理 API 和宿主工具协议兼容。

调研日期：2026-08-07。

## 功能复杂度

- 级别：核心功能。
- 选择理由：变更横跨 Embed Gateway、MCP 执行器、WebSocket 协议、SDK UI、数据库审计主体和副作用确认状态机。
- 最低调研要求：官方 MCP 规范、官方 SDK 实现、成熟 Agent HITL 实践，并分析安全、兼容性、审计和断线行为。

## 参考依据

### 来源 1：Model Context Protocol Tools 规范

- 类型：官方协议规范。
- 名称：Model Context Protocol - Tools。
- 链接：https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- 版本或发布日期：2025-06-18 规范版本；调研日期：2026-08-07。
- 核心做法：服务端通过 `tools/list` 暴露工具名称、描述和输入 Schema，客户端通过 `tools/call` 发起调用；规范建议对敏感操作保留人在回路、向用户展示工具输入并在执行前取得确认。
- 对本项目的启发：MCP 工具描述应由后端运行时绑定给模型；SDK 只负责确认交互，不能接触 MCP endpoint、认证头或代替后端调用远程服务。

### 来源 2：MCP Python SDK

- 类型：官方 SDK 与成熟实现。
- 名称：Model Context Protocol Python SDK。
- 链接：https://github.com/modelcontextprotocol/python-sdk
- 版本或发布日期：v2 当前稳定线，兼容 2026-07-28 及更早规范；本仓库仍固定 `mcp>=1.28.1,<2.0.0`；调研日期：2026-08-07。
- 核心做法：同一客户端 API 可以连接 URL、stdio 或测试内存服务，并通过结构化参数调用工具；v1 与 v2 迁移被明确区分。
- 对本项目的启发：本次保持现有 Streamable HTTP 客户端与 v1 依赖，不借功能接入扩大为 SDK 大版本迁移；Gateway 复用已有 `RepositoryMcpExecutor`。

### 来源 3：LangChain Human-in-the-loop

- 类型：成熟 Agent 框架官方实践。
- 名称：LangChain Human-in-the-loop middleware。
- 链接：https://docs.langchain.com/oss/python/langchain/human-in-the-loop
- 版本或发布日期：当前在线文档；调研日期：2026-08-07。
- 核心做法：按工具策略暂停运行，允许批准、编辑或拒绝；批准后恢复同一 thread，拒绝时合成 ToolMessage 反馈给模型并继续运行；文档明确建议副作用工具拒绝后不要自动重试。
- 对本项目的启发：确认必须暂停当前工具执行并保留模型上下文；批准、拒绝和超时都应转成工具结果后恢复同一轮，而不是另发 REST 请求开启新对话。

### 来源 4：本仓库宿主工具与 MCP 既有边界

- 类型：现有生产设计与实现约束。
- 名称：Phase 2B 宿主页面工具设计、MCP 管理与对话运行时。
- 链接：`docs/harness/requests/2026-07-28-agent-sdk-host-tools/`、`docs/harness/requests/2026-07-29-front-mcp-management/`、`apps/backend/app/modules/conversation/runtime.py`。
- 版本或发布日期：仓库当前版本；调研日期：2026-08-07。
- 核心做法：宿主工具由浏览器执行并使用独立审计；MCP 工具由后端执行并使用服务端凭据、策略、确认和审计；普通 REST 对话已经能绑定 MCP 工具。
- 对本项目的启发：不能把 MCP 包装成浏览器宿主工具。Gateway 应统一编排但按工具类型分流，并保留两套独立执行器和审计事实。

## 现状结论

- `load_runtime_context()` 已能加载 `context.mcp_tools`。
- REST 对话会把 MCP、Skill 工具传入 `stream_graph()`，因此后端 MCP 调用链已存在。
- Embed Gateway 当前只构建宿主工具与 Skill 工具集合，`stream_embed_chat()` 也只接收 `host_tools`，因此模型看不到 MCP。
- 前端 bridge 的 system prompt 还限制为只能调用 `navigate_to_page`，并会拒绝其他确认请求。
- MCP 审计和确认当前只关联 `sys_users.id`，而 Embed token 的 `sub` 是 `platform_end_users.id`，直接复用会产生主体外键错配。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| A：Gateway 统一编排并按类型分流 | MCP 留在后端执行；复用策略、加密凭据和审计；确认后可恢复同一模型循环 | 需要扩展 WebSocket 确认载荷、Gateway 协调器和审计主体模型 | 高，采用 |
| B：把 MCP 包装成宿主工具 | 表面上可复用现有 SDK 宿主调用协议 | 暴露或转发服务端能力到浏览器，混淆凭据、权限和审计边界 | 低，不采用 |
| C：MCP 调用留在 REST 对话并单独确认 | 对现有 Gateway 改动少 | 浮动对话仍看不到 MCP；确认后不能自然恢复原模型上下文 | 低，不采用 |

## 最终决策

- 选择方案：A，Gateway 统一编排并按 `mcp_tool`、`skill_tool`、`host_tool` 分流。
- 无副作用 MCP 工具在后端自动执行；有副作用 MCP 工具创建现有 confirmation 和 audit，通过 WebSocket 等待用户决定后恢复同一工具循环。
- SDK 默认展示内置确认面板；接入方提供 `onConfirmationRequired` 时完全接管 UI，避免重复确认。
- MCP 审计和确认增加可空 `platform_end_user_id`，并将 `user_id` 改为可空；检查约束要求两类主体必须且只能存在一个。
- 工具名称冲突时安全失败：冲突名称不进入模型工具集合，其他工具继续可用并记录来源明确的错误日志。
- 不迁移到 MCP Python SDK v2，不修改 MCP 管理 API，不把宿主工具并入 MCP 审计。

## 剩余风险

- WebSocket 断线发生在用户确认前后时，必须保证未执行的副作用工具不会被自动重试。
- 现有 MCP confirmation 使用十分钟有效期，需要让 Gateway 等待超时、数据库状态和 SDK UI 状态一致。
- 协议新增字段虽然是附加字段，仍需验证旧 SDK 对未知字段的兼容性。
- 真实远程 MCP 服务、PostgreSQL 外键迁移和浏览器确认 UI 需要端到端联调，单元测试不能替代。
