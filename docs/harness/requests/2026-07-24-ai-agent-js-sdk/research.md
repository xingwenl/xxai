# 业界调研记录

## 调研问题

- 本次要解决什么问题？
  - 创建一个 AI Agent JS SDK，允许第三方网站快速嵌入 AI 聊天功能，并支持工具调用
- 调研结果将影响哪些范围、架构、接口或实现决策？
  - SDK 的整体架构设计
  - 类型系统设计
  - 传输层选择（WebSocket vs SSE）
  - UI 框架选择
  - 打包配置

## 功能复杂度

- 级别：核心功能
- 选择理由：这是一个完整的 SDK 项目，包含通信层、状态管理、UI 层等多个模块
- 最低调研要求：至少参考 1-2 个成熟开源项目

## 参考依据

### 来源 1

- 类型：成熟开源项目
- 名称：agentpage
- 链接：https://www.npmjs.com/package/agentpage
- 版本或发布日期：1.0.0（4 months ago）
- 调研日期：2026-07-24
- 核心做法：
  - core/web 分层架构，core 零 DOM 依赖
  - 完整的回调系统（onRound、onToolCall、onText、onMetrics 等）
  - TypeBox 做工具参数的运行时类型校验
  - Agent Loop 编排、工具注册分发
  - 支持内置工具和自定义工具
  - 完整的 metrics 指标收集
- 对本项目的启发：
  - 分层架构很重要，保持 core 纯 TypeScript
  - 完善的回调系统提升用户体验
  - 类型安全的工具定义是必要的
  - 连接状态管理和重连机制

### 来源 2

- 类型：官方设计文档
- 名称：agent-js-sdk-integration-brief.md
- 链接：.worktrees/configurable-agent-platform/docs/design/agent-js-sdk-integration-brief.md
- 版本或发布日期：2026-07-24
- 调研日期：2026-07-24
- 核心做法：
  - 推荐 headless + floating UI 模式
  - WebSocket 协议设计（消息信封、事件类型）
  - 鉴权方案：短期 embed token
  - 宿主工具规范（JSON Schema、副作用等级）
- 对本项目的启发：
  - 协议设计已经很详细，按这个实现
  - 先做第二阶段 A，后续再加工具
  - 架构要支持后续扩展

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：双打包（核心+UI 层合一） | 架构清晰，易于扩展，单一入口简单 | 需要处理 Vue 打包到 SDK 的问题 | 高 |
| 方案 B：三层分离（核心包+UI 包独立） | 最灵活，用户按需选择 | 维护成本高，第一版太复杂 | 中 |

## 最终决策

- 选择方案：方案 A（双打包，核心+UI 层合一）
- 选择原因：
  - 第一版需要简单直接，单一入口对用户友好
  - 架构保持分层，未来仍可拆分为独立包
  - 符合设计文档的分期策略
- 不选择其他方案的原因：
  - 方案 B 过度设计，第一版不需要如此复杂
- 对后续 spec、plan 或人工确认的影响：
  - 明确使用 TypeScript + Vue 3 + Vite
  - 明确传输层优先 WebSocket，预留 SSE 接口

## 剩余风险

- 资料时效性：agentpage 是 4 个月前发布的，比较新
- 与本项目上下文的差异：agentpage 是浏览器原生 Agent，我们是连接后端的 SDK
- 尚未验证的假设：Vue 组件打包成 SDK 的最佳实践需要进一步验证

## 2026-07-31 增量调研：token 与终端用户身份

### 调研问题

- SDK 的 `getToken` 应获取什么凭据，凭据由哪一层签发？
- `external_user_id` 应由 SDK 生成、浏览器提交，还是由接入方服务端确定？
- 在不破坏现有 WebSocket 协议的前提下，如何让 SDK 使用方式不再产生身份误解？

### 参考来源

#### 来源 3：OAuth 2.0 Token Exchange

- 类型：IETF 标准 RFC 8693
- 链接：https://www.rfc-editor.org/rfc/rfc8693
- 版本或发布日期：RFC 8693，2020-09
- 调研日期：2026-07-31
- 核心做法：由受信任的服务端将已有身份或授权上下文交换为面向目标服务、范围更窄、生命周期更短的访问令牌。
- 对本项目的启发：`client_secret` 只能留在接入方服务端；浏览器通过接入方后端拿到短期 Embed Access Token，不能把长期 Client 凭据放进 SDK。

#### 来源 4：OAuth 2.0 Security Best Current Practice

- 类型：IETF 标准 RFC 9700
- 链接：https://www.rfc-editor.org/rfc/rfc9700
- 版本或发布日期：RFC 9700，2025-01
- 调研日期：2026-07-31
- 核心做法：限制访问令牌生命周期和作用域，避免在不可信客户端暴露长期凭据，并通过服务端校验授权上下文。
- 对本项目的启发：Embed Token 继续使用 5 至 15 分钟的短 TTL；终端用户标识必须来自接入方已验证的业务会话，而不是信任浏览器任意传入的字符串。

#### 来源 5：现有项目 Embed Token 设计与联调规范

- 类型：本仓库设计与运行手册
- 链接：`docs/design/agent-sdk-phase-2-requirements.md`、`docs/runbooks/agent-sdk-local-integration.md`
- 版本或发布日期：2026-07-26 / 2026-07-31
- 调研日期：2026-07-31
- 核心做法：`(platform_id, external_user_id)` 映射为平台终端用户；`POST /api/v1/embed/tokens` 由接入方服务端调用，浏览器只接收 `access_token`；`GET /api/agent-token` 仅用于本地 Demo。
- 对本项目的启发：不应让 SDK 直接承担终端用户身份认证；SDK 只负责把 token provider 返回的短期令牌用于 WebSocket `auth`。

### 方案比较

| 方案 | 做法 | 收益 | 限制 | 结论 |
|---|---|---|---|---|
| A | SDK 自动生成 `external_user_id` 并换 token | 接入代码少 | 无法证明用户身份，跨刷新/设备不稳定，易造成越权 | 不采用 |
| B | 浏览器把 `external_user_id` 直接传给公共 token 接口 | Demo 简单 | 用户可篡改身份；长期 secret 虽留在服务端，身份仍未绑定登录态 | 仅保留为本地 Demo |
| C | 接入方后端从登录态取得 `external_user_id`，调用 token exchange；SDK 仅调用 `getToken(context)` | 身份边界清晰，兼容短期 token 和 WebSocket 协议 | 接入方需要提供一个自己的 token 代理接口 | 采用 |

### 最终决策

采用方案 C。SDK 的 `getToken` 接收可选上下文，便于接入方 token 代理知道当前平台、Agent 和业务用户，但 SDK 不把 `external_user_id` 拼进网关连接或自行生成身份。`external_user_id` 的真实来源、校验和持久化由接入方后端负责；Embed 后端继续将其映射为 `PlatformEndUser`，并把内部 ID 放入 token 的 `sub`。

本次不修改 token JWT claims、WebSocket `auth` 事件或数据库模型，仅修正 SDK 接口文档、调用约定和边界测试。
