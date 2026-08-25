# 设计说明

## 目标

- 为 `apps/ai-sdk` 提供 embed client 与 agent 的基本信息：token 授权认证成功后，SDK 即可读取 client 名称、限额（`max_tokens_per_minute`、`max_connections`、`token_ttl_seconds`）、agent 名称/slug/描述，以及当前配额窗口的限额与用量（`quota_model_tokens_limit`、`quota_message_limit`、`quota_connection_limit`、`quota_token_issue_limit` 对应的 limit/current）。
- 影响对象：通过 embed SDK WebSocket 链路（`/ws/agents/{agent_id}`）建立的连接。
- 完成后应产生可验证结果：`session_ready` 事件携带 `client`/`agent`/`quota` 段；SDK 暴露 `clientInfo`/`agentInfo`/`quota` 读取接口并触发 `client_info` 事件；聊天窗口 `.xxai-header-name` 优先显示 client 名称，无 client 名称时回退到 `title`。
- 调研结论见 `research.md`：参考 Claude Code Agent SDK、Vercel AI SDK、OpenAI Runs API、LangGraph，采用"随 `session_ready` 内联下发"方案（方案 A），零额外请求、向后兼容。

## 范围

### 网关 WebSocket 协议（后端）

- `apps/backend/app/modules/gateway/router.py`：token 认证成功、发送 `session_ready` 前，用短生命周期 session 查询 `PlatformEmbedClient` 与 `Agent`，并用现有 `quota_service` 读取当前窗口配额快照，组装进 `session_ready` payload：

```json
{
  "client": {
    "clientId": "client_xxx",
    "name": "ToolVerse",
    "tokenTtlSeconds": 600,
    "maxTokensPerMinute": 120,
    "maxConnections": 50
  },
  "agent": {
    "agentId": 11,
    "name": "客服助手",
    "slug": "support-bot",
    "description": "负责售后问题"
  },
  "quota": {
    "windowSeconds": 60,
    "resources": {
      "connection": { "limit": 10, "current": 2 },
      "message": { "limit": 60, "current": 12 },
      "model_tokens": { "limit": 10000000, "current": 123456 },
      "token_issue": { "limit": 120, "current": 3 }
    }
  }
}
```

- 配额读取：
  - `connection`/`message`/`model_tokens` 用现有 `quota_service.peek()`，维度为 `platform/client/agent/end_user`（与网关 `QuotaDimensions` 一致）；
  - `token_issue` 的 limit 用 `client.max_tokens_per_minute or settings.quota_token_issue_limit`（与 `apps/backend/app/modules/embed/services.py` 的 `build_token_quota_service` 一致），current 用同一窗口的 `peek`，维度为 `platform/client/agent`（签发时不含 end_user，见 `issue_embed_token`）。
- 降级规则（不阻塞连接）：
  - `quota_enabled=false`（`quota_service is None`）→ `quota` 段为 `null`；
  - Redis/数据库查询失败 → 对应段为 `null`，连接继续正常建立；
  - client 或 agent 查询不到 → 对应段为 `null`（token 已认证过作用域，正常情况下不会发生）。
- 配额窗口语义：`window = 当前时间 // quota_window_seconds`，是**时间窗口**（默认 60 秒），不是会话；同一窗口内跨会话累计计数，窗口过期自动重置（Redis key 带窗口号）。

### SDK（apps/ai-sdk）

- `src/core/types.ts`：新增 `EmbedClientInfo`、`AgentInfo`、`QuotaResourceUsage`、`QuotaUsage` 类型。
- `src/core/client.ts`：`session_ready` 分支解析并保存 `client`/`agent`/`quota`；新增只读 getter `clientInfo`/`agentInfo`/`quota`；新增 `client_info` 事件（payload 为 `{client, agent, quota}`）。
- `src/ui/components/ChatWidget.vue`：`.xxai-header-name` 优先显示 `agent.clientInfo?.name`，缺失时回退到 `title` prop（默认 `AI Assistant`）。回退逻辑抽为纯函数 `resolveHeaderName` 以便单测。
- `src/ui/index.ts`：`createChatUI` 无需改动（回退逻辑在组件内完成）；前端调用方不传 `title` 时，连接建立后自动显示 client 名称。

### SDK UI 展示形态（增量）

- `src/ui/components/QuotaRing.vue`（新增）：头部右侧常驻的圆形进度条，展示消息配额 `已用/限额`（如 `12/60`），圆环中心显示数字，颜色随用量变化（`<70%` 用主题色、`70-90%` 橙色、`>=100%` 红色），悬浮提示「每 60 秒窗口重置」；`limit` 不存在或 `<=0` 时不渲染。
- `src/ui/quota-ring.ts`（新增）：纯函数 `quotaRingState(current, limit)` 计算 `{ratio, color, text}`，便于单测。
- `src/ui/components/ChatWidget.vue`：头部 QuotaRing 挂载点已于 2026-08-24 由用户注释停用（默认不展示，组件与单测保留，可随时恢复）；`.xxai-header-name` 仍优先显示 client 名称。
- `src/ui/components/ChatMessageList.vue`：消息为空（`messages.length === 0` 且无 pending）时，居中展示 agent 头像、名称与描述（新增 props `agentName`/`agentDescription`，从 `ChatWidget` 传入；数据源为 `agent.agentInfo`，旧网关无 `agentInfo` 时名称回退 `title`、描述不展示）；一旦有消息，空状态自动消失。

### 测试与文档

- 后端：`apps/backend/tests/gateway/` 新增 session 信息组装单测（payload 结构、配额禁用回退、Redis 不可用回退、token_issue limit 回退）。
- SDK：`apps/ai-sdk/src/core/__tests__/` 新增解析与事件用例；`src/ui/__tests__/` 新增 `resolveHeaderName` 回退用例。
- 本 request 文档（`docs/harness/requests/2026-08-24-ai-sdk-session-info/`）。

## 非目标

- 不做配额实时推送（窗口内后续消费不主动刷新 current），当前需求仅展示连接建立时的快照。
- 不修改 REST 签发型接口与 `EmbedTokenResponse` 结构。
- 不新增数据库表或字段（无数据模型变化）。
- 不改动前端 `agent-navigation-bridge.tsx`（其未传 `title`，改造后自动显示 client 名称；该文件现有未提交改动与本次无关，不混入）。

## 风险

- 兼容性风险：旧版 SDK 收到新增字段会忽略，不回归；新版 SDK 连接旧网关（无 `client`/`agent`/`quota` 段）时各 getter 为 `undefined`，头部回退到 `title`。
- 数据风险：配额为快照，可能与窗口内实际计数略有时间差；仅用于展示，不影响网关已有的拦截逻辑。
- 回归风险：`session_ready` 组装在认证成功后执行，需确保查询失败不阻塞连接（降级为 null）；网关其余事件流与配额拦截逻辑不变。

## 停点判断

- 是否涉及架构边界变化：否，改动在既有网关连接生命周期与 SDK 客户端内部完成。
- 是否涉及数据模型变化：否。
- 是否涉及 API 契约变化：是，`session_ready` 出站事件新增 `client`/`agent`/`quota` 字段。
- 是否涉及鉴权或权限行为变化：否，数据查询沿用 token 认证后的作用域，不新增权限语义。
- 结论：进入实现前需人工确认（API 契约变化）。

## 验收标准

- token 认证成功后，`session_ready` 事件携带 `client`（clientId/name/tokenTtlSeconds/maxTokensPerMinute/maxConnections）与 `agent`（agentId/name/slug/description）。
- `quota_enabled=true` 且 Redis 正常时，`session_ready` 携带 `quota`：`windowSeconds` + `connection`/`message`/`model_tokens`/`token_issue` 四个资源的 `{limit, current}`；`token_issue.limit` 取 `client.max_tokens_per_minute`，未配置时回退到 `settings.quota_token_issue_limit`。
- `quota_enabled=false` 或 Redis 不可用时，`quota` 段为 `null`，连接正常建立，不阻塞、不报错。
- SDK 在收到 `session_ready` 后可通过 `clientInfo`/`agentInfo`/`quota` 读取上述信息，并触发 `client_info` 事件；旧网关 payload 无新字段时读取值为 `undefined`，不抛错。
- `.xxai-header-name` 在 `clientInfo.name` 存在时显示 client 名称；不存在时回退到 `title` prop。
- 现有 WebSocket 事件流、配额拦截（`connection`/`message`/`model_tokens`）、REST 接口行为不回归。

## 变更记录

### 2026-08-24 第 2 次变更

- 变更原因：用户实测后认为配额展示不需要，手动注释 QuotaRing 展示
- 变更内容：`ChatWidget` 头部 QuotaRing 挂载点注释（默认不展示）；保留网关 `session_ready` 数据下发、SDK `quota`/`clientInfo`/`agentInfo` 解析与 `client_info` 事件、头部 client 名称、空状态 agent 名称/描述；`QuotaRing.vue`/`quota-ring.ts` 及其单测保留为可选组件
- 影响章节：范围（SDK UI 展示形态）、验收标准
- 是否触发人工确认：否（纯 UI 展示调整，无 API/数据模型/鉴权变化）
- 关联计划更新：已同步更新 `plan.md`

### 2026-08-24 第 1 次变更

- 变更原因：用户确认展示形态——头部圆形进度条 + 空状态 agent 名称描述
- 变更内容：新增 `QuotaRing.vue`（头部右侧常驻，消息配额 `已用/限额`，三色用量状态 + 窗口 tooltip）与 `quota-ring.ts` 纯函数；`ChatMessageList` 空状态展示 agent 名称/描述；`ChatWidget` 挂载圆环并透传 agent 名称/描述；其余配额资源（model_tokens/token_issue/连接数）仍由 SDK `quota` 提供但不展示
- 影响章节：范围（SDK UI 展示形态）、验收标准、停点判断（无新增契约）
- 是否触发人工确认：否（纯 UI 展示，无 API/数据模型/鉴权变化）
- 关联计划更新：已同步更新 `plan.md`

### 初始版本

- 时间：2026-08-24
- 变更原因：首次创建 ai-sdk session 信息下发设计
- 变更内容：确定扩展 `session_ready` payload（`client`/`agent`/`quota` 三段），配额窗口为时间窗口（默认 60 秒）而非会话；SDK 暴露 `clientInfo`/`agentInfo`/`quota` 与 `client_info` 事件；头部优先显示 client 名称并回退 `title`
- 影响章节：全部
- 是否触发人工确认：是（API 契约变化）
