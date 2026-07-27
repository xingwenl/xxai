# 设计说明

## 目标

在现有多平台 Agent 后端和 `apps/ai-sdk` 骨架上，实现可供第三方网页真实接入的 Phase 2A：Embed Client、短期 token、平台最终用户身份、版本化 WebSocket 网关、有限断线恢复，以及 SDK 的真实流式聊天和引用展示。

目标调用方包括平台管理员、接入方服务端、第三方网页和最终用户。完成后，本地端到端环境必须能证明：接入方服务端换取 token，浏览器 SDK 建立连接，发送消息，接收 LangGraph 流式回答和引用，取消请求，并在短断线后恢复。

方案来自 `research.md`：采用 FastAPI 原生 WebSocket、自定义 `ai-agent.v1` 协议、Direct Line 风格短期 token 和 Redis Streams 有界恢复，不引入 Socket.IO 或托管聊天通道。

## 范围

### 后端数据模型

新增：

- `PlatformEmbedClient`：平台接入凭据、密钥哈希、Origin、TTL、启用状态和限制。
- `PlatformEmbedClientAgent`：Client 可访问 Agent 白名单。
- `PlatformEndUser`：平台内 `external_user_id` 到稳定内部 ID 的映射。

调整：

- `Conversation.user_id` 改为可空。
- `Conversation.platform_end_user_id` 新增为可空外键。
- 添加数据库约束，确保两种主体恰好存在一个。
- 保留所有已有内部用户 Conversation 行为。

Phase 2A 不增加持久化 WebSocket event 表；事件重放使用 Redis Streams。

### 管理与 token API

- `POST /api/v1/platforms/{platform_id}/embed-clients`：创建 Client，只在响应中展示一次 secret。
- `GET /api/v1/platforms/{platform_id}/embed-clients`：分页查询，不返回 secret/hash。
- `PATCH /api/v1/platforms/{platform_id}/embed-clients/{client_id}`：修改名称、Origin、TTL、状态和限制。
- `POST /api/v1/platforms/{platform_id}/embed-clients/{client_id}/rotate-secret`：轮换 secret，旧 secret 立即失效。
- `PUT /api/v1/platforms/{platform_id}/embed-clients/{client_id}/agents/{agent_id}`：绑定 Agent。
- `DELETE /api/v1/platforms/{platform_id}/embed-clients/{client_id}/agents/{agent_id}`：解除绑定。
- `POST /api/v1/embed/tokens`：使用 Client 凭据换取短期 token。
- `POST /api/v1/embed/tokens/{jti}/revoke`：平台管理员撤销未过期 token。
- `GET /api/v1/embed/conversations/{conversation_id}/messages`：embed token 读取自己的消息快照。

Client 管理 API 使用现有后台 JWT 和平台管理员权限；token exchange 使用独立 Client 认证依赖；消息快照使用 embed token。

### WebSocket API

- 地址：`/api/v1/ws/agents/{agent_id}`。
- 握手验证 Origin 和 `ai-agent.v1` subprotocol。
- 连接后 5 秒内必须收到 `auth`。
- 认证成功发送 `session_ready`，失败使用稳定 close code 和服务端审计。
- 支持 `message_send`、`message_cancel`、`ping`。
- 输出 `session_ready`、`message_started`、`message_delta`、`citation`、`tool_call`、`tool_result`、`message_completed`、`error`、`pong`。
- 每个连接最多一个进行中的生成请求；并发提交返回 `request_in_progress`。
- 客户端断开或取消后，取消模型生成和后续工具调用。

### Token claims

固定：`iss=ai-base`、`aud=agent-embed`、`protocol_version=1`。动态：`sub`、`platform_id`、`agent_id`、`client_id`、`origin_hash`、`jti`、`iat`、`nbf`、`exp`。

token TTL 默认 600 秒，允许范围 300 至 900 秒。签名算法来自服务端固定配置，不能由 token header 动态放宽。后台 access token 不得访问 embed endpoint，embed token 不得访问后台管理 API。

### 线协议

- JSON 信封字段使用 camelCase，事件 type 使用 snake_case。
- `protocolVersion` 当前只能为 `1`。
- `requestId` 由客户端生成并用于幂等、取消和事件关联。
- `sequence` 在单个 conversation 事件流中递增。
- payload 使用 Pydantic/TypeScript 判别联合定义，禁止无边界 `Record<string, unknown>` 作为核心事件最终契约。
- 单个入站消息最大 64 KiB，文本消息最大 16 KiB。
- 服务端错误统一包含 `code`、`message`、`retryable` 和可选 `details`，不返回堆栈或内部密钥。

### Redis 状态

- `agent:events:{conversation_id}`：Redis Stream，保留 15 分钟，最多 1000 条。
- `agent:embed:revoked:{jti}`：撤销标记，TTL 到 token exp。
- `agent:request:{principal}:{request_id}`：幂等/进行中状态，有界 TTL。
- 连接本身不作为长期业务事实，不要求进程重启后恢复 socket。

### SDK

- 保留现有 `createAgentClient()` 公共入口，移除 Mock 行为。
- WebSocket endpoint 接受 HTTPS/WSS 基地址并规范化为固定路径，禁止拼接 token 查询参数。
- `connect()` 获取 token、建立连接、发送 auth 并等待 session_ready 后才 resolve。
- 指数退避带随机抖动；主动 `disconnect/destroy` 不自动重连。
- token 无效或过期时只刷新一次，避免无限认证循环。
- 完整处理协议事件、游标去重、恢复失败消息快照、取消和结构化错误。
- `headless` 和 `floating` 达到验收；UI 展示流式内容、连接状态、引用和停止生成。
- SDK 不在 localStorage、URL、console 或错误对象中保留 token。
- 包名、全局变量名和 README 在实现第一步统一；不在 Phase 2A 同时增加 React 包。

## 非目标

- 不实现 `host_tools_register`、`host_tool_call`、宿主工具确认和宿主工具审计，这些属于 Phase 2B。
- 不实现管理后台页面，Phase 2A 只提供配置 API。
- 不实现 CDN 发布、React 包、多标签页协调、完整配额计费和长期事件归档。
- 不拆独立 WebSocket 微服务，不引入 Socket.IO。
- 不改变 MCP 现有副作用确认语义。
- 不把平台长期 Client secret 或后台 JWT 暴露给浏览器。

## 风险

- Conversation 主体模型变更可能影响已有内部用户查询和外键约束。
- token audience 或 Origin 校验错误可能导致跨平台访问。
- 客户端断开与数据库事务生命周期处理不当可能留下半完成消息或继续调用工具。
- Redis 不可用时恢复能力会降级；新会话是否允许继续必须使用明确配置，不能静默改变语义。
- 反向代理可能影响 WebSocket upgrade、Origin 和 idle timeout，需要真实部署联调。
- SDK 当前缺少自动化测试，替换 Mock 传输的回归面较大。

## 停点判断

- 架构边界变化：是，新增 WebSocket 会话网关和 Redis 事件层。
- 数据模型变化：是，新增 Embed Client、平台最终用户并修改 Conversation 主体。
- API 契约变化：是，新增管理、token、快照和 WebSocket 协议。
- 鉴权或权限变化：是，新增 Client 认证和 embed token 权限域。

结论：`research -> spec -> plan` 可以完成；进入实现前必须等待人工确认。当前 `meta.json.approvalGranted=false`。

## 验收标准

### 身份隔离

- Client secret 只在创建/轮换时返回一次，数据库只保存密码学哈希。
- token 的 platform、agent、client、subject、audience、issuer、exp、jti 或 Origin 任一不匹配时，连接被拒绝。
- embed token 不能调用后台管理 API，后台 access token 不能伪装 embed 主体。
- 内部用户与平台最终用户只能读取和继续自己的 Conversation。

### 协议与运行时

- WebSocket 与 HTTP/SSE 使用同一个 Conversation Runtime，引用、grounded 和 MCP 结果语义一致。
- 正常回答事件顺序为 started -> zero or more delta/citation/tool events -> completed，sequence 严格递增。
- 相同主体和 requestId 不会启动两次生成。
- 取消和断开后不继续生成或调用后续工具。
- Redis 游标有效时补发遗漏事件；游标失效时明确返回 recovered=false 并可读取消息快照。

### SDK

- `connect()` 连接真实后端，不存在 Mock 定时回复。
- SDK 可发送消息、增量展示、显示引用、停止生成并短断线重连。
- 重放事件不会重复显示；销毁后无连接、定时器、DOM 或事件监听残留。
- token 不进入 URL、localStorage、console 和构建产物。
- `npm run type-check`、`npm run test`、`npm run build` 全部通过。

### 工程验证

- 后端定向测试、全量 pytest、Ruff、定向 Black、Poetry check、OpenAPI 和 Alembic history 通过。
- FastAPI TestClient 覆盖 WebSocket 认证、消息、取消、跨平台和 Origin 拒绝。
- 本地真实 Redis + PostgreSQL 环境完成迁移与端到端联调。
- 浏览器测试覆盖连接、流式显示、断网重连、token 过期和 destroy 清理。
- `verify.md` 记录真实命令和输出，`acceptance.md` 明确剩余风险后才能标记 done。

## 变更记录

### 初始版本

- 时间：2026-07-26。
- 变更原因：第一阶段合并后，建立可跨窗口执行的 JS SDK WebSocket Phase 2A request。
- 变更内容：定义 Embed Client、平台最终用户、token exchange、WebSocket 协议、Redis 恢复和 SDK 真实接入。
- 影响章节：全部。
- 是否触发人工确认：是，涉及架构、数据模型、API 和鉴权。

### 2026-07-27 方案确认

- 变更原因：用户确认 Phase 2A 的架构、数据模型、API 和鉴权方案，解除实现前审批停点。
- 变更内容：确认使用原生 `ai-agent.v1` WebSocket、Embed Client 服务端换取 5 至 15 分钟 token、`PlatformEndUser` 与 Conversation 双主体、Redis Streams 15 分钟事件窗口；本 request 不实现宿主工具。
- 影响章节：范围、非目标、风险、停点判断、验收标准。
- 是否触发人工确认：是，已于 2026-07-27 获得用户确认。
- 关联计划更新：Task 0 审批步骤完成，进入 `implement` 阶段。
