# 业界调研记录

## 调研问题

- 本次要解决什么问题：ai-sdk 通过 embed token 授权认证成功后，需要获取 embed client 与 agent 的基本信息（名称、限额、用量等），并把聊天窗口头部 `.xxai-header-name` 显示的名称改为 client 名称。
- 调研结果将影响哪些范围、架构、接口或实现决策：WebSocket 协议（`apps/backend/app/modules/gateway/router.py` 的 `session_ready` 事件）、配额服务读取方式（`apps/backend/app/modules/quota/service.py`）、SDK 类型与客户端（`apps/ai-sdk/src/core/types.ts`、`apps/ai-sdk/src/core/client.ts`）、UI 头部展示（`apps/ai-sdk/src/ui/components/ChatWidget.vue`），以及验收标准与实施计划。

## 功能复杂度

- 级别：复杂 / 架构级（策略 B）
- 选择理由：跨后端网关协议、配额服务、SDK 三端联动；`session_ready` 出站事件新增 `client`/`agent`/`quota` 段属于 API 契约变化，触发人工确认；不涉及数据模型与鉴权语义变化（沿用 token 认证结果，无新增表字段）。
- 最低调研要求：参考至少两个成熟 Agent/LLM 框架在"认证/会话建立后如何回传连接元数据、限额与用量"的实现，比较"随认证响应内联下发"与"客户端再发一次查询请求"两条路线。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：Claude Code Agent SDK — Session metadata 与 RateLimitStatus（Python/TS）
- 链接：https://code.claude.com/docs/zh-TW/agent-sdk/python
- 版本或发布日期：持续维护，调研日期 2026-08-24
- 核心做法：Agent SDK 在建立会话（session）时随 SDK 对象/连接返回会话元数据；限流状态（`RateLimitStatus` / `overage_status`）由 SDK 提供读取接口，客户端无需额外轮询，即可获知当前是否超限、重置时间等信息。
- 对本项目的启发：连接/会话级元数据与配额状态由服务端随会话建立一起下发，客户端本地缓存即可，避免额外请求；本项目同样在 `session_ready`（连接建立成功事件）内联下发 client/agent/配额快照。

### 来源 2

- 类型：官方发布说明与规范
- 名称：Vercel AI SDK 5.0 — Usage Information
- 链接：https://vercel.com/blog/ai-sdk-5（usage-information 相关章节）
- 版本或发布日期：AI SDK 5.0，调研日期 2026-08-24
- 核心做法：模型调用的 usage（token 用量）作为响应的一部分内联返回，而不是通过单独的 usage 端点查询；客户端从完成响应中直接读取 prompt/completion token 计数。
- 对本项目的启发：用量信息"随响应/事件内联返回"是业界默认做法；本项目在连接建立事件中内联返回当前窗口用量（current）与限额（limit）。

### 来源 3

- 类型：官方 API 规范
- 名称：OpenAI Assistants API / Runs API — usage 字段
- 链接：https://platform.openai.com/docs/api-reference/runs
- 版本或发布日期：持续维护，调研日期 2026-08-24
- 核心做法：`Run` 对象在请求完成时直接携带 `usage`（`prompt_tokens`、`completion_tokens`、`total_tokens`），客户端从 run 响应 JSON 中读取，无独立用量查询接口。
- 对本项目的启发：用量/限额信息附加在已完成/已建立的对象事件上，保持"零额外请求"；本项目把配额快照附加在 `session_ready` 事件上。

### 来源 4

- 类型：成熟开源项目文档
- 名称：LangGraph — usage_metadata on AIMessage
- 链接：https://docs.langchain.com/oss/python/langgraph（AIMessage metadata 说明）
- 版本或发布日期：持续维护，调研日期 2026-08-24
- 核心做法：token 使用量通过 callback 记录后附加在 `AIMessage.metadata.usage_metadata` 上随消息一起返回，由框架在消息层面统一携带，调用方无需另查。
- 对本项目的启发：元数据随消息/事件一起走的模式已验证可行；本项目连接级信息（client/agent）与窗口配额随 `session_ready` 一起走。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：扩展 `session_ready` payload，认证成功后由网关直接下发 client/agent/配额快照 | 零额外 HTTP 请求；无 CORS 与鉴权二次开销；与连接生命周期一致；向后兼容（旧 SDK 忽略新字段，新 SDK 兼容旧网关缺失字段） | `session_ready` payload 变大；配额为快照（窗口内变化需后续事件刷新） | 高 |
| 方案 B：认证成功后 SDK 再调 REST 接口获取 client/agent/配额 | 数据与 WebSocket 协议解耦 | 多一次请求与往返延迟；需处理 CORS、token 传递、失败重试；服务端需新增 REST 契约（另一处 API 变化） | 低 |
| 方案 C：前端静态配置 client 名称与限额 | 实现最简单 | 限额/用量无服务端事实来源；名称易与后台配置漂移；无法展示真实用量 | 低 |

## 最终决策

- 选择方案：方案 A——扩展 WebSocket `session_ready` payload，token 认证成功后由网关一次性下发 `client`（clientId/name/tokenTtlSeconds/maxTokensPerMinute/maxConnections）、`agent`（agentId/name/slug/description）与 `quota`（windowSeconds + connection/message/model_tokens/token_issue 的 limit/current 快照）。
- 选择原因：四个业界来源（Claude Code Agent SDK、Vercel AI SDK、OpenAI Runs API、LangGraph）均验证"连接/响应事件内联携带元数据与用量"的形态；本项目配额本身就在网关侧维护（`QuotaService`），在同一连接内读取无需额外鉴权；零 CORS 风险、零额外请求。
- 不选择其他方案的原因：方案 B 引入新的 REST 契约与往返成本，且配额快照仍需在网关侧计算；方案 C 无服务端事实来源，无法满足"限额、用量"诉求。
- 对后续 spec、plan 或人工确认的影响：`session_ready` 事件新增字段属 API 契约变化，`plan -> implement` 前需人工确认；不涉及数据模型与鉴权逻辑变化（配额读取沿用连接层 token 作用域）。

## 剩余风险

- 资料时效性：Claude Code 与 OpenAI 文档持续更新，调研日期 2026-08-24 为当前状态；实施时以官方最新接口说明为准。
- 与本项目上下文的差异：业界示例多为 REST 响应内联 usage，本项目为 WebSocket 事件内联配额快照，语义一致但载体不同。
- 尚未验证的假设：配额快照为"当前窗口"的 limit/current，窗口内后续消费不会实时推送——当前需求（头部名称 + 基本信息展示）不依赖实时刷新，若后续需要实时用量，可另加事件。
