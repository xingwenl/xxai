# Phase 2B 宿主页面工具设计说明

## 变更记录

### 2026-09-19 宿主工具审计时间列读写口径修复（fix）

- 变更原因（两个相连的时间列缺陷，都表现为"页面执行成功、模型只看到工具执行失败"）：
  1. **读侧相减**：真实链路日志显示 `Host tool dispatched ... audit_status=running` 之后直接出现 `Tool step completed ... status=failed`，既没有 `Host tool completed/failed` 也没有 `Host tool wait timed out`，而页面确实回传了结果。失败点是等待上限换算 `existing.expires_at - utc_naive_now()`：审计列是 `TIMESTAMP WITH TIME ZONE`（asyncpg 读回 aware），naive 与之相减抛 `TypeError: can't subtract offset-naive and offset-aware datetimes`；异常发生在带日志的 `try` 之外，被 AgentLoop 归一成失败的 `ToolOutcome`。
  2. **写侧口径**：读侧修好后又出现 `Host tool result ignored reason=no_pending_future` —— 等待窗口被算成已过期（`waited_seconds=0.0`），Future 在页面回传前就被释放。根因是写入 `expires_at` 用的是 naive UTC 值，而 asyncpg 的 `timestamptz_encode` 执行 `obj.astimezone(utc)`，对 naive 值按**本地时间**解释（东八区整体偏移 8 小时），读回即"8 小时前已过期"。该写法由 `f9faa5f`（2026-07-29）引入，当时是为规避相反方向的错误（naive 列写入 aware 值会抛同一个 TypeError）。
- 变更内容：
  - 新增 `host_tool/services.py::as_utc()` 与 `wait_timeout_seconds()`：读侧把 naive/aware 统一成带时区 UTC，已过期按 0 处理；同时移除只服务 naive 列的 `utc_naive_now()`，避免再次混用两种口径。
  - 写侧统一为带时区 UTC：`dispatcher.py` 的 `expires_at` 改用 `datetime.now(UTC) + 10min`，`repositories.py` 的 `started_at`/`completed_at` 改用 `datetime.now(UTC)`。
  - `host_tool/models.py` 把 `expires_at/started_at/completed_at` 显式声明为 `DateTime(timezone=True)` 并补中文 comment，使 ORM 映射与迁移（`TIMESTAMP WITH TIME ZONE`）一致（不产生 DDL 变更，无新增迁移）。
  - `gateway/dispatcher.py`：等待上限计算、下发与等待整体纳入 `try/except Exception`（异常打堆栈后抛出）；新增 `Host tool future registered` / `Host tool future released`（含 `pending_keys`）、`Host tool wait window already expired`（含 `expires_at`/`now_utc`）；`Host tool dispatched` 增加 `wait_timeout_seconds`；MCP 确认等待上限改用同一助手。
  - `gateway/router.py`：`Host tool result ignored reason=no_pending_future` 增加 `future_found`/`future_done`/`pending_keys`，可直接区分"callId 不匹配"与"请求已结束、结果迟到"。
  - `gateway/runtime.py` 在 `failed` 工具步骤后新增 `Tool step failed detail`（`outcome_status` + 真实 `outcome_error`），落库字段仍是既有 `tool_failed`；`agent_runtime/loop.py` 在工具调用抛异常处补 `Tool invocation raised`（含堆栈）。
- 影响章节：范围（WebSocket 协议执行链路、失败可见性）、风险（时间列读写口径）、验收标准（工程验证）。
- 是否触发人工确认：否。`host_tool/models.py` 的改动只是把 ORM 映射对齐既有迁移列类型（`DateTime(timezone=True)`，无 DDL、无数据迁移），未改变 API 契约与权限语义；用户已明确要求"确认原因并补齐关键日志"。
- 关联计划更新：已同步更新 `plan.md` 的「2026-09-19 宿主工具审计时间列读写口径修复计划」。

### 2026-09-19 宿主工具执行失败排障日志（fix 增量）

- 变更原因：绑定修复上线后，页面方法（如 `page_snapshot`）已能在模型工具表中出现并被调用，但用户反馈"执行失败"。当前链路的失败原因全部不可见：页面回传的 `host_tool_error` 只写审计表不写日志；网关分发、等待超时、迟到结果被忽略等分支均无日志；工具步骤落库的失败原因被统一成"工具执行失败"；SDK 在工具已从注册表消失时静默返回，服务端只能等到 10 分钟超时。
- 变更内容：
  - 网关分发器（`app/modules/gateway/dispatcher.py`）新增 `Host tool dispatched`、`Host tool completed`、`Host tool failed`（含 `error_code`/`error_message`/`result_bytes`/`duration_ms`）、`Host tool wait timed out`、`Host tool invocation failed`（含堆栈）以及 callId 复用参数不一致的错误日志。
  - 网关路由（`app/modules/gateway/router.py`）新增 `Host tool result received`、`Host tool error received`（含 `code`/`message`）、`Host tool result too large`、`Host tool result ignored reason=...`、`Host tool confirmation resolved/ignored`。
  - 请求编排（`app/modules/gateway/runtime.py`）在工具步骤落库处新增 `Tool step completed`，把决定前端文案的 `status` 与 `error_code`/`error_message` 写入日志。
  - AgentRuntime（`app/modules/agent_runtime/tool_loop.py`、`composition.py`）在"工具未在执行目录中"与"工具调用抛异常"两处记录工具名、callId、错误码与堆栈。
  - SDK（`apps/ai-sdk/src/core/client.ts`）在宿主工具生命周期的调用、参数校验失败、结果发送、执行失败四处输出 `[xxai-agent][host-tool]` 前缀日志；把"执行前工具已不存在"的静默返回改为回传 `host_tool_not_registered`，避免服务端只能等到超时。
- 影响章节：范围（WebSocket 协议执行链路）、风险（排障可视化）、验收标准（工程验证）。
- 是否触发人工确认：是，用户明确要求"打上关键日志，下次直接可以查日志"，日志与静默返回修复按该指令实施；页面工具预算语义（见下）涉及安全预算放行口径，待用户确认后再实现。
- 待确认变更（未实现）：`apps/ai-sdk/src/core/page/runtime.ts` 的预算窗口从实例首次调用开始计时且不重置，导致长生命周期页面在 `maxDurationMs`（默认 120s，接入方常配 60s）之后所有页面工具调用永久返回 `page_tool_budget_exceeded`，只有刷新页面才能恢复。候选方案：A. 每次用户请求开始时重置预算窗口（恢复"单次任务预算"语义）；B. 改为滑动窗口（最近 `maxDurationMs` 内最多 `maxCalls` 次）。
- 关联计划更新：已同步更新 `plan.md` 的「2026-09-19 宿主工具执行失败排障增量计划」。

### 2026-09-19 宿主工具未绑定给模型修复（fix）

- 变更原因：页面通过 `host_tools_register` 注册的宿主工具虽然被网关接受（日志 `Temporary host tools enabled for connection` / `Host tools active for connection`），但 `stream_embed_chat` 在 `runtime_tools` 与 `host_tools` 之间二选一，宿主工具既不进 `bind_tools` 也不进工具调用器，模型无法产生 `host_tool_call`，表现为"注册成功但工具永远不被调用"。该行为由 `f8068b5`（2026-08-07 接入内置工具与 Embed MCP）引入，早于本 request 的验收结论。
- 变更内容：
  - 新增 `merge_model_tools()`，把入口工具（内置/MCP/技能）与页面宿主工具合并成模型实际可调用的集合，同名冲突沿用 `filter_conflicting_runtime_tools` 的整体剔除策略。
  - system prompt 的"可用工具清单"改为仅在连接注册了宿主工具时追加，且清单取实际绑定集合，保证提示词与 `bind_tools` 一致。
  - 新增关键排障日志：`Embed request host tools`（连接级已注册/已授权集合）、`Model tools bound`（runtime/host/bound 三个集合）。
  - 重放健壮性：Stream 不存在（Redis `no such key`）、重放抛异常、`latestSequence` 非数字（旧客户端 Redis Stream ID 游标）时降级为不重放并记录告警，不再让整个 WebSocket 建连失败。
- 影响章节：范围（WebSocket 协议）、风险、验收标准（工程验证）。
- 是否触发人工确认：是，2026-09-19 用户确认修复方向并要求补充关键日志。
- 关联计划更新：已同步更新 `plan.md` 的「2026-09-19 修复增量实施计划」。

### 2026-07-31 第 1 次变更

- 变更原因：增加可信临时页面的低配置工具接入方式。
- 变更内容：新增 Embed Client 后端 `allow_temporary_tools` 开关；开启后工具定义仅保存在连接内存，token 不维护 `host_tool_names`，SDK 每次 WebSocket 连接自动注册；后端根据签名 token claim 建立连接级内存策略。
- 影响章节：目标、范围、风险、验收标准。
- 是否触发人工确认：是，涉及 WebSocket 工具授权语义；已由用户明确确认。
- 关联计划更新：补充 SDK transport 重连注册、网关临时策略和对应测试。

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
- 注册成功的宿主工具必须与入口工具一起绑定给模型（`merge_model_tools()`）；只写进 system prompt 不算注册成功，模型必须能产生 `host_tool_call`。
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
- 注册成功的宿主工具必须出现在模型的 `bind_tools` 工具表中，并有回归测试固定该行为。
- 后端与 SDK 都使用 JSON Schema Draft 2020-12 校验参数，SDK 不执行未注册名称。
- `destroy()` 后无 WebSocket、计时器、事件监听和待执行工具残留。

### 工程验证

- 后端迁移、模型、服务、权限、状态机和 WebSocket 测试通过；SDK type-check、Vitest、build 通过。
- 测试覆盖至少包括跨平台拒绝、三重白名单、确认竞态、重复 callId、重复结果、超时、结果大小限制和断线场景。
- `verify.md` 记录真实命令、输出、失败项和未覆盖风险；`acceptance.md` 对每条验收标准给出结论。

## 变更记录

### 2026-07-31 后台切换工具状态修复（fix）

- 变更原因：后台管理端切换工具启用状态时会提交完整策略对象，后端将未变化的 `input_schema` 误判为 Schema 变化，导致工具始终被重置为禁用。
- 变更内容：仅当 `input_schema` 的结构内容确实变化时，才撤销策略启用状态；相同 Schema 的状态更新保留请求中的 `is_enabled`。
- 影响章节：管理 API、状态与副作用、工程验证。
- 是否触发人工确认：否，不改变 API 契约、数据模型或权限语义。

### 2026-07-29 审计时间兼容与异常回传修复（fix）

- 变更原因：真实 PostgreSQL 联调时发现审计时间列为 `TIMESTAMP WITHOUT TIME ZONE`，带时区时间导致审计写入失败；runtime 异常也未向客户端暴露错误 payload。
- 变更内容：统一宿主工具审计时间为 UTC 无时区值；网关将 runtime 异常编码为非空 `error` payload。
- 影响章节：状态与副作用、SDK 与协议、工程验证。
- 是否触发人工确认：否，不改变权限和 API 契约。

### 2026-07-28 Demo 自动调用接入（modify）

- 变更原因：Phase 2B Demo 已能注册本地工具，但 token proxy 未携带 host tool claim，无法验证 AI 自动调用。
- 变更内容：Demo token proxy 接收 host_tool_names；index.html 请求三个 Demo 工具；新增本地 seed 脚本配置策略、Agent 绑定和 Client 绑定。
- 影响章节：SDK、管理 API、验收标准。
- 是否触发人工确认：否，复用已确认的三重白名单设计，不改变生产权限语义。

### 2026-07-28 WebSocket timer 调用修复（fix）

- 变更原因：浏览器触发 WebSocket 非正常关闭时，原生 timer 方法以错误 receiver 调用，导致 Illegal invocation。
- 变更内容：在 WebSocketTransport 构造时将 setTimeout 和 clearTimeout 绑定到 globalThis，并增加回归测试。
- 影响章节：SDK、风险、验收标准。
- 是否触发人工确认：否，不改变协议、数据模型或权限语义。

### 2026-07-28 初始版本

- 变更原因：Phase 2A 已验收，开始独立 Phase 2B 宿主页面工具 request。
- 变更内容：建立后台策略、Client/token 白名单、SDK 执行、确认、状态机和独立审计边界。
- 影响章节：全部。
- 是否触发人工确认：是，用户已于 2026-07-28 确认推荐方案并授权进入实现。
