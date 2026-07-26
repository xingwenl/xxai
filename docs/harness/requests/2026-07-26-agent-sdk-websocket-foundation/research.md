# 业界调研记录

## 调研问题

- 浏览器嵌入式 Agent 如何安全获得短期凭据，而不暴露平台长期密钥？
- FastAPI 与现有 Conversation Runtime 如何增加 WebSocket，同时保持 HTTP/SSE 事件语义一致？
- 多实例部署下如何处理短断线、事件游标、幂等和恢复失败？
- 现有 Mock SDK 应继续演进，还是改用 Socket.IO 或第三方托管聊天通道？

调研结果影响架构、数据模型、API 契约、鉴权、SDK 传输和部署方式。

## 功能复杂度

- 级别：核心功能。
- 选择理由：跨后端、Redis、数据库、浏览器 SDK 和第三方接入方服务端；任何身份或重放错误都可能造成跨平台数据泄露或重复副作用。
- 最低调研要求：官方协议/安全资料、成熟嵌入式聊天案例、断线恢复案例和现有代码审计。

## 当前实现审计

- 第一阶段后端已有 `POST /api/v1/agents/{agent_id}/chat` JSON/SSE、Conversation/Message、知识库引用、MCP 确认和审计。
- Conversation 当前只能关联内部 `sys_users`，不能可靠表示第三方平台最终用户。
- `apps/ai-sdk` 已有 Client、ToolRegistry、Vue floating UI 和构建产物。
- SDK `WebSocketTransport` 使用本地 Mock 回复，没有建立网络连接；`SSETransport` 直接抛出未实现错误。
- SDK 处理 `text_delta`，后端 SSE 使用 `message_delta`，当前没有稳定统一的线协议。
- SDK 没有自动化测试，工具注册没有发送到后端，也没有参数校验、确认和结果回传。

## 参考依据

### 来源 1：FastAPI WebSockets

- 类型：官方框架文档。
- 链接：https://fastapi.tiangolo.com/advanced/websockets/
- 版本或发布日期：当前在线文档，调研日期 2026-07-26。
- 核心做法：FastAPI 原生支持 WebSocket endpoint、依赖注入、断开异常和多客户端连接管理。
- 对本项目的启发：第一版可将网关留在现有 FastAPI 单体，复用仓储和运行时；连接管理必须抽象，不能把业务状态只放进 endpoint 局部变量。

### 来源 2：OWASP WebSocket Security Cheat Sheet

- 类型：权威安全实践。
- 链接：https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html
- 版本或发布日期：当前在线版本，调研日期 2026-07-26。
- 核心做法：只使用 WSS；握手验证 Origin；执行消息级授权；限制消息大小、频率和连接数；记录 WebSocket 业务事件；谨慎使用压缩。
- 对本项目的启发：Origin 白名单和连接认证都不够，Agent、Conversation 和工具仍需逐消息校验。token 不应放查询字符串，生产默认关闭压缩。

### 来源 3：RFC 8725 JSON Web Token Best Current Practices

- 类型：IETF 标准最佳实践。
- 链接：https://www.rfc-editor.org/rfc/rfc8725.html
- 版本或发布日期：2020-02。
- 核心做法：显式限制算法，验证 issuer、subject、audience，并为不同 JWT 类型使用互斥验证规则。
- 对本项目的启发：embed token 使用独立 audience 和校验入口，不能复用后台 access token 的宽松解析结果。

### 来源 4：Microsoft Bot Framework Direct Line 3.0 Authentication

- 类型：成熟生产产品官方文档。
- 链接：https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-direct-line-3-0-authentication?view=azure-bot-service-4.0
- 版本或发布日期：Direct Line API 3.0，调研日期 2026-07-26。
- 核心做法：服务端长期 secret 可换取单会话、会过期的 token；浏览器使用短期 token；token 可绑定用户和可信域名。
- 对本项目的启发：采用 Embed Client secret -> 短期 token 的服务端交换模式，token 绑定平台、Agent、最终用户和 Origin。

### 来源 5：Socket.IO Connection State Recovery

- 类型：成熟开源实时通信框架官方文档。
- 链接：https://socket.io/docs/v4/connection-state-recovery
- 版本或发布日期：Socket.IO 4.x，恢复能力自 4.6.0 提供。
- 核心做法：短断线后恢复 session 和遗漏 packet，同时明确恢复可能失败，客户端必须支持全量状态同步。
- 对本项目的启发：协议同时定义“游标补发成功”和“无法恢复后读取持久消息”两条路径，不能假设所有重连都能续传。

### 来源 6：Redis Streams

- 类型：官方数据结构文档。
- 链接：https://redis.io/docs/latest/develop/data-types/streams/
- 版本或发布日期：当前在线文档，调研日期 2026-07-26。
- 核心做法：使用单调 ID 追加事件，支持按 ID 范围读取、阻塞消费和有界裁剪。
- 对本项目的启发：Redis Stream 适合作为 15 分钟有界事件重放层；PostgreSQL Conversation/Message 继续作为长期业务事实。

### 来源 7：JSON Schema Draft 2020-12

- 类型：官方规范。
- 链接：https://json-schema.org/draft/2020-12
- 版本或发布日期：2022-06-16 发布版本。
- 核心做法：定义标准 Schema 和验证词汇。
- 对本项目的启发：Phase 2B 的宿主工具参数在后端和 SDK 使用同一 draft，避免两端验证语义漂移。

### 来源 8：MDN WebSocket constructor

- 类型：浏览器平台权威文档。
- 链接：https://developer.mozilla.org/en-US/docs/Web/API/WebSocket/WebSocket
- 版本或发布日期：Baseline，自 2015-07 广泛可用；调研日期 2026-07-26。
- 核心做法：浏览器构造函数只接受 URL 和可选 subprotocol，不能设置任意 Authorization 请求头。
- 对本项目的启发：token 不能依赖自定义握手请求头。选用固定子协议，连接后立即发送 auth 事件，并设置严格认证超时。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| A：FastAPI 原生 WebSocket + 自定义版本协议 + Redis Streams + 演进现有 SDK | 复用现有后端、Conversation Runtime 和 SDK；协议边界可控；无额外网关服务 | 需要自行实现认证、重放、限流和协议测试 | 高，推荐 |
| B：引入 Socket.IO 服务端和客户端 | 重连、心跳和恢复能力成熟 | 引入 Socket.IO 专有协议和 Python ASGI 适配层；与现有原生 SSE/SDK 协议重复 | 中 |
| C：使用 Direct Line 类托管聊天通道 | 嵌入式 token 与 Web Chat 生态成熟 | 外部平台锁定；难以复用当前 LangGraph、MCP 审计和平台模型 | 低 |

## 关键决策

### 决策 1：选择方案 A

继续使用 FastAPI 原生 WebSocket，定义版本化 `ai-agent.v1` 协议，复用现有运行时。借鉴 Socket.IO 恢复语义，但不引入其线协议。

### 决策 2：服务端交换短期 token

平台管理员创建 Embed Client；接入方服务端持有长期 secret；浏览器只获得 5 至 15 分钟 token。token 使用独立 audience，绑定平台、Agent、最终用户、Client、Origin 和 jti。

### 决策 3：连接后 auth，而不是 URL token

握手先校验 Origin 和固定 subprotocol。连接后 5 秒内发送 auth；认证前拒绝业务消息。该方式避免 token 出现在 URL、代理访问日志和浏览器历史中。

### 决策 4：Redis 只保存短期传输状态

事件流、撤销 jti 和连接状态存 Redis 并设置 TTL；Conversation/Message、Client 配置和最终用户映射存 PostgreSQL。恢复窗口失效时，从 PostgreSQL 消息快照恢复。

### 决策 5：先完成 2A，再创建 2B request

宿主工具会新增独立策略、状态机和审计模型，不与基础连接 request 混合实现。完整需求保留在总纲，Phase 2B 在 2A 协议稳定后单独调研和确认。

## 不选择其他方案的原因

- 不选择 Socket.IO：当前没有 rooms、广播等强需求，专有协议收益不足以抵消双端依赖和协议锁定。
- 不选择第三方托管通道：会复制或绕开现有平台隔离、Conversation、知识库和工具审计，迁移成本高。
- 不把 token 放 URL：泄露面明显，且与现有交接文档和 OWASP 建议冲突。
- 不把所有 delta 永久写数据库：成本高且不必要，持久消息与短期传输事件职责应分离。

## 对 spec、plan 和人工确认的影响

- 必须新增 Embed Client、Client-Agent 绑定、平台最终用户数据模型，并调整 Conversation 主体约束。
- 必须新增 token exchange、管理 API、WebSocket 线协议和消息快照 API。
- 必须新增独立 embed token 鉴权、Origin、限流和撤销行为。
- 上述内容触发架构、数据模型、API 和鉴权人工确认；文档完成后停在 `plan`，不得直接实现。

## 剩余风险

- FastAPI 单体的单机连接能力尚未压测，Phase 2A 先建立指标和压测基线，不提前拆网关。
- Redis Stream 的 TTL、条数和消息大小需要真实流量校准，首版采用保守默认值。
- 现有 Conversation `user_id` 非空，迁移和仓储改造必须覆盖内部用户兼容测试。
- 当前 SDK 没有测试基础设施，Phase 2A 第一批任务必须先建立 Vitest 和 WebSocket fake server 测试。
- 真实反向代理的 WebSocket timeout、Origin 转发和断开语义需要部署环境联调。
