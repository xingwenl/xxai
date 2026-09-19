# Phase 2B 宿主页面工具实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在既有 `ai-agent.v1` WebSocket 和 SDK 上实现受三重白名单约束、可确认、可幂等、可审计的宿主页面工具调用。

**Architecture:** PostgreSQL 保存平台工具策略、Client/Agent 绑定和 `HostToolCallAudit` 最终状态；FastAPI 网关负责每条消息的主体授权、状态迁移和事件编排；SDK 只执行本页面显式注册且与后台 Schema 一致的函数。宿主工具与 MCP 使用不同模型、服务、协议事件和审计查询。

**Tech Stack:** FastAPI、Pydantic、SQLAlchemy、Alembic、`jsonschema`、原生 WebSocket、TypeScript、Vitest、现有 Redis replay abstraction。

## 2026-07-31 增量实施计划

1. 在 SDK WebSocket 测试中先验证普通 `registerTools()` 首次连接和重连自动发送内存工具。
2. 在 Embed Client 模型、管理 API 和管理页面增加 `allow_temporary_tools`；SDK 类型和注册路径不增加临时模式配置。
3. 在 WebSocket transport 中按工具名缓存注册消息，连接恢复后补发所有内存工具；显式断开不清理实例内存注册，便于再次连接恢复。
4. 在后端增加连接级临时策略构造器；仅当签名 token claim `temporary_tools: true` 时使用，校验工具名称、描述、Object Schema 和副作用等级，不写入数据库。
5. 执行 SDK focused/full tests、类型检查、后端宿主工具测试、Ruff/Black 和 diff 检查，更新 verify/acceptance。

---

## 2026-09-19 宿主工具审计时间列读写口径修复计划

1. 读侧：在 `app/modules/host_tool/services.py` 新增 `as_utc()`（naive/aware 统一为带时区 UTC）与 `wait_timeout_seconds()`（缺失回退默认值，已过期归零），并删除只服务 naive 列的 `utc_naive_now()`。
2. 写侧：`app/modules/gateway/dispatcher.py` 的 `expires_at` 改为 `datetime.now(UTC) + 10min`；`app/modules/host_tool/repositories.py` 的 `started_at`/`completed_at` 改为 `datetime.now(UTC)`；`app/modules/host_tool/models.py` 把这三列显式声明为 `DateTime(timezone=True)`（对齐迁移，无 DDL）。
3. 在 `app/modules/gateway/dispatcher.py` 用 `wait_timeout_seconds()` 替换宿主工具与 MCP 确认两处手写换算；把"计算等待上限 → 下发 host_tool_call → 等待 Future"整段纳入同一 `try/except Exception`（`CancelledError` 仍原样抛出），消除"下发后无任何日志却失败"的静默窗口。
4. 补齐时间/Future 生命周期日志：`Host tool dispatched`（含 `wait_timeout_seconds`）、`Host tool wait window already expired`（含 `expires_at`/`now_utc`）、`Host tool future registered` / `Host tool future released`（含 `pending_keys`）。
5. 在 `app/modules/gateway/router.py` 的 `no_pending_future` 分支补 `future_found`/`future_done`/`pending_keys`；在 `app/modules/gateway/runtime.py` 的 `failed` 步骤后补 `Tool step failed detail`；在 `app/modules/agent_runtime/loop.py` 补 `Tool invocation raised`（含堆栈）。
6. 单元测试（`tests/gateway/test_host_tool_timeout.py` 的假仓库按 asyncpg 语义模拟两种列类型）：
   - TIMESTAMPTZ 形状下写入必须带时区，等待窗口保持 ~600s，页面结果能回填、Future 被回收；
   - 历史 naive 列读回值仍能正常工作；
   - `as_utc`/`wait_timeout_seconds` 覆盖 naive、aware、None、已过期（`tests/host_tool/test_services.py`）。
7. 验证：`ruff`、`pytest tests/gateway tests/host_tool tests/mcp tests/agent_runtime tests/conversation tests/embed`、全量 `pytest`；结果写入 `verify.md`（含"修复前必失败"的证据）。
8. 同步 `apps/ai-sdk/README.md` 15.6 日志表：补 `wait_timeout_seconds`、`Host tool wait window already expired`、`Host tool future registered/released`、`Tool step failed detail` 与对应排障顺序。

---

## 2026-09-19 宿主工具执行失败排障增量计划

1. 网关分发器补齐宿主工具全生命周期日志：下发（工具名/sideEffect/确认态/审计状态/参数摘要）、成功（结果字节数/耗时）、失败（错误码/错误信息/字节数/耗时）、等待超时、异常堆栈、callId 复用参数不一致。
2. 网关路由补齐页面回调日志：成功回传、失败回传（错误码+原因）、结果过大、以及三条静默忽略路径（缺 callId、无待唤醒 Future、审计非 running）与确认结果。
3. 请求编排在工具步骤落库处记录 `Tool step completed`（status + error_code + error_message），与前端工具卡片文案同源。
4. AgentRuntime 在"工具不在执行目录"与"工具抛异常"两处记录工具名/错误码/堆栈。
5. SDK 客户端补齐 `[xxai-agent][host-tool]` 日志，并把执行前工具丢失的静默返回改为 `host_tool_not_registered` 错误回传。
6. 更新 `apps/ai-sdk/README.md` 15.6：新增"工具被调用但执行失败"的服务端/浏览器日志对照表与常见失败码说明。
7. 验证：后端 `tests/gateway tests/host_tool tests/agent_runtime tests/conversation tests/embed`、SDK `vitest` + `type-check`、Ruff；结果写入 `verify.md`。
8. 待确认项（不在本次实现范围）：页面工具预算窗口重置语义（每次请求重置 vs 滑动窗口）。

---

## 2026-09-19 修复增量实施计划

1. 在 `app/modules/gateway/runtime.py` 新增 `merge_model_tools()`，把入口工具与宿主工具合并后绑定给模型；同名冲突沿用既有整体剔除策略。
2. 在 `stream_embed_chat()` 使用合并结果，补 `Model tools bound` 日志（runtime/host/bound 三个集合 + requestId），system prompt 清单改为实际绑定集合。
3. 在 `app/modules/gateway/router.py` 补 `Embed request host tools` 日志，并把 `int(replay_latest)` 改为容错解析；重放异常降级为不重放。
4. 在 `app/modules/gateway/replay.py` 捕获 Stream 不存在（`no such key`），按「无可重放事件」返回并记录告警。
5. 补回归测试：`tests/gateway/test_chat_flow.py`（合并工具、模型 `bind_tools` 含宿主工具）、`tests/gateway/test_replay.py`（缺失 Stream、非数字游标）。
6. 执行 focused/full 后端测试、Ruff/Black，更新 `verify.md` 与 `acceptance.md`。

---

## 文件结构

- 后端新增 `app/modules/host_tool/{models,schemas,repositories,services,router}.py`，分别负责持久化模型、HTTP/WS 数据契约、数据库访问、授权/状态机和管理路由。
- 后端新增 Alembic migration，创建策略、绑定和调用审计表；不修改 MCP 表。
- 修改 `app/modules/embed/schemas.py`、`services.py` 和 `security.py`，把 Client 允许的宿主工具名称按交集写入 token claim。
- 修改 `app/modules/gateway/schemas.py`、`router.py` 和新增 `host_tools.py`，隔离协议解析、工具调用协调和 WebSocket 生命周期；同时修改 `app/modules/conversation/runtime.py` 与 `app/modules/gateway/runtime.py`，把授权宿主工具注入模型并在工具调用处暂停/恢复。
- SDK 修改 `types.ts`、`protocol.ts`、`tool-registry.ts`、`websocket.ts`、`client.ts`，新增 JSON Schema 验证、超时/取消、确认回调和结果回传。
- 后端新增 `tests/host_tool/` 与 `tests/gateway/test_host_tools.py`；SDK 扩展现有 protocol、websocket、client 测试。

## 实施步骤

### 本次轻量 Bugfix

- 修改 `apps/backend/app/modules/host_tool/repositories.py`：比较更新前后的 `input_schema` 结构，仅在内容变化时撤销启用状态。
- 新增 `apps/backend/tests/host_tool/test_repositories.py`：覆盖完整策略提交但 Schema 未变化时仍能启用工具。
- 验证 `cd apps/backend && poetry run pytest tests/host_tool -q` 与对应 Ruff 检查。

### Task 1: 定义宿主工具领域模型和 Schema

- [ ] 新增 `HostToolPolicy`、`AgentHostTool`、`EmbedClientHostTool`、`HostToolCallAudit`。`HostToolCallAudit.call_id` 建立唯一约束；`status` 使用 CheckConstraint 限制七种状态；参数只保存脱敏 JSON 和 SHA-256 摘要，结果保存脱敏 JSON。
- [ ] 在 `host_tool/schemas.py` 定义 `SideEffect`、`ConfirmationPolicy`、策略 CRUD、绑定请求、审计读取模型，以及 `HostToolRegistration`、`HostToolCallPayload`、`ConfirmationResolvePayload`、`HostToolResultPayload`。
- [ ] 为工具名称使用 `^[a-zA-Z][a-zA-Z0-9_.-]{0,127}$`，Schema 必须是 object，策略描述和消息字段限制长度；输入/输出 Schema 的 JSON 序列化大小限制为 64 KiB。
- [ ] 为 schema 变更定义 `schema_fingerprint = sha256(canonical_json(schema))`，变更后将策略置为 disabled，避免旧页面实现继续被授权。
- [ ] 测试模型约束、Schema 字段校验、状态枚举、名称和大小限制：`cd apps/backend && poetry run pytest tests/host_tool/test_schemas.py -q`。

### Task 2: 新增数据库迁移和 Repository

- [ ] 新增 `migrations/versions/20260728_0010_host_tools.py`，创建四张表、外键、索引和唯一约束；`HostToolCallAudit` 的 `platform_end_user_id`、`conversation_id` 可空但必须按 token 主体写入，绑定表使用 `(client_id, tool_id)` 与 `(agent_id, tool_id)` 唯一约束。
- [ ] 在 `HostToolRepository` 实现按 platform 过滤的策略查询、Client/Agent 工具绑定、注册工具求交、按 `call_id + platform_id + agent_id + platform_end_user_id` 查询调用、条件状态更新和审计列表。
- [ ] 条件更新只允许合法迁移：`requested -> awaiting_confirmation|running`、`awaiting_confirmation -> running|rejected|expired`、`running -> succeeded|failed`；更新行数不是 1 时返回冲突，不执行函数。
- [ ] 测试 repository 的跨平台查询、唯一 callId、状态迁移和确认竞态，并执行 `poetry run alembic check`。

### Task 3: 实现工具策略管理 API 和 token claim

- [ ] 在 `host_tool/router.py` 增加策略 CRUD、Agent/Client 绑定和审计列表，所有入口使用当前后台用户的平台管理员依赖，并让 Repository 再次按 `platform_id` 限制资源。
- [ ] 扩展 `EmbedTokenRequest.host_tool_names: list[str]`；签发 token 时读取 Client 绑定工具，只将 `requested_names ∩ client_allowed_names` 写入 `host_tools` claim；未授权请求名称不报错但不进入 claim，避免客户端借声明探测后台策略。
- [ ] 在 token 验证后的网关上下文中读取 `host_tools`，禁止从 WebSocket auth payload 读取工具白名单；补充 token claim 单元测试和管理 API 权限测试。
- [ ] 验证命令：`poetry run pytest tests/embed tests/host_tool/test_routes.py -q`。

### Task 4: 实现后端授权、状态机和审计服务

- [ ] 在 `host_tool/services.py` 实现 `validate_registration()`：工具名必须存在于 token claim、启用的 Agent 绑定和启用的策略；注册的描述、inputSchema 指纹必须与策略一致；返回当前连接可用工具集合。
- [ ] 实现 `request_host_tool()`：按 callId 查询已有记录；同参数返回原状态，参数摘要不同返回冲突；参数用同一 Draft 2020-12 validator 校验；`none` 进入 `running`，其余进入 `awaiting_confirmation`；所有参数先脱敏再写审计。
- [ ] 实现 `resolve_host_tool_confirmation()` 与 `record_host_tool_result()`：使用条件更新抢占状态，确认拒绝/过期为终态；只有 `running` 调用接受结果；结果超限或错误分别落 `failed`，重复结果只返回原状态。
- [ ] 结果脱敏递归处理 `password/token/secret/api_key/authorization/cookie` 等字段，并限制 JSON 序列化后大小为 32 KiB。
- [ ] 测试三重白名单、Schema 变更失效、所有状态迁移、确认竞态、重复 callId、重复结果、超时和脱敏。

### Task 5: 扩展 WebSocket 网关事件

- [ ] 在 `gateway/schemas.py` 增加事件类型和明确 payload；`validate_incoming_message` 拒绝过大的消息、未知必需字段和非法 callId，保留未知可选字段忽略行为。
- [ ] 新增 `gateway/host_tools.py` 协调器：处理注册、生成调用事件、确认解决、结果/错误回传；调用事件带 `callId`、`requestId`、工具名、参数、sideEffect 和 `requiresConfirmation`，确认事件只带脱敏摘要。
- [ ] 在 `gateway/router.py` 的每条消息分支调用协调器，传入认证 token claims 和当前连接主体；连接关闭时只取消 `none` 的未执行任务，不重试副作用调用，并保留审计终态可查询。
- [ ] 对 `host_tool_call` 设置单调用并发限制，执行超时使用后端配置的默认值；所有事件通过现有 envelope/replay store 发送，不能把 token 或原始敏感参数放日志。
- [ ] 用 FastAPI WebSocket 测试覆盖 Origin、跨平台、注册、确认、结果和断线场景：`poetry run pytest tests/gateway/test_host_tools.py -q`。

### Task 6: 将宿主工具接入 Conversation Runtime

- [ ] 扩展 `RuntimeContext` 增加宿主工具候选列表，不改变 MCP 工具字段；网关在连接认证和注册完成后只把授权交集转换成 LangChain function tool 描述。
- [ ] 修改 `run_graph()` 的工具循环，使 `invoke_tool_fn` 接收 `tool_kind="host"`、`call_id`、工具名和参数；宿主调用返回 `awaiting_confirmation` 时向上层返回可恢复的 pending 状态，不写 assistant completion。
- [ ] 修改 `stream_embed_chat()` 支持 `host_tool_executor` 回调：模型产生宿主 tool call 时 yield `host_tool_call`/`confirmation_required`，等待同一 `callId` 的页面结果，再把 `ToolMessage` 放回 graph 继续生成；页面错误进入模型可见的 ToolMessage，但不自动重试副作用调用。
- [ ] 为每轮生成绑定 request cancel event；取消、WebSocket 断开或 token 主体失效时停止后续模型调用和宿主调用，并保留 `HostToolCallAudit` 的最终状态。
- [ ] 测试模型返回宿主 tool call、自动工具回传后继续回答、确认后继续回答、拒绝后继续回答、页面错误和断开取消；命令：`poetry run pytest tests/gateway/test_host_tool_runtime.py -q`。

### Task 7: 实现 SDK 注册和执行器

- [ ] 在 `types.ts` 增加 `HostToolCall`、`ConfirmationRequired`、`ToolCallStatus`、`onConfirmationRequired` 和 `resolveToolCall` 类型；不改变既有 `registerTool` 公共入口。
- [ ] 在 `tool-registry.ts` 增加 JSON Schema 2020-12 validator、注册 Schema 指纹、工具超时和 AbortController 管理；注册后由 transport 发送 `host_tools_register`，未获服务端认可的工具不执行。
- [ ] 在 `protocol.ts` 增加六类事件 payload 解析和严格字段校验；在 `websocket.ts` 增加注册发送、`host_tool_call` 分发、确认/结果回传、callId 去重和 `destroy` 清理。
- [ ] 执行器流程固定为：查找注册函数 -> 校验参数 -> 等待确认（如需）-> `execute(params, context)` -> 超时/AbortSignal -> 结果大小和敏感字段过滤 -> 回传 `host_tool_result`；任一步失败均回传 `host_tool_error`，不自动重试。
- [ ] 在 `client.ts` 暴露 `resolveToolCall(callId, approved)`、`onToolConfirmation` 事件和调用状态查询；UI 仅展示确认和状态，不自行批准。
- [ ] 测试 `npm run type-check && npm run test -- --run src/core/__tests__/protocol.test.ts src/core/__tests__/websocket.test.ts src/core/__tests__/client.test.ts`。

### Task 8: 集成验证和文档闭环

- [ ] 执行后端 `poetry run pytest`、`poetry run ruff check .`、`poetry run black --check app tests`、`poetry run alembic check`。
- [ ] 执行 SDK `npm run type-check`、`npm run test`、`npm run build`。
- [ ] 运行本地 FastAPI/SDK fake WebSocket 集成场景，记录注册、自动工具、确认工具、拒绝、重复 callId、断线和 destroy 证据。
- [ ] 将真实命令、预期、实际输出和例外写入 `verify.md`；按 spec 验收标准逐条更新 `acceptance.md`；最后将 `meta.json.phase` 更新为 `acceptance`、`status` 更新为 `done`（若有未解除阻塞则保留 `active/blocked`）。

## 测试步骤

- 后端单元/集成：`cd apps/backend && poetry run pytest tests/host_tool tests/gateway/test_host_tools.py tests/embed -q`。
- 后端全量与静态检查：`cd apps/backend && poetry run pytest && poetry run ruff check . && poetry run black --check app tests && poetry run alembic check`。
- SDK：`cd apps/ai-sdk && npm run type-check && npm run test && npm run build`。
- 预期：所有命令返回码为 0；失败项必须记录在 `verify.md`，不得以“未执行”代替结果。

## 回滚说明

- 代码回滚按本 request 的连续提交逆序执行；数据库使用 Alembic downgrade 删除四张 Phase 2B 表，不回滚 Phase 2A migration。
- 回滚前先停止新宿主工具 token 签发或关闭策略 API，避免已有 token 在代码回滚后继续发送未知事件。
- SDK 回滚必须同时回滚协议事件解析和后端网关，保持 `ai-agent.v1` 的 2A 事件兼容；MCP 表和审计数据不做删除。

## 人工确认点

- 已确认：2026-07-28，范围为后端权威授权、SDK 执行、三重白名单、独立状态/审计和 JSON Schema 2020-12。
- 实现中不得扩大为任意脚本执行、MCP 复用、断线副作用自动重试或管理后台页面。
