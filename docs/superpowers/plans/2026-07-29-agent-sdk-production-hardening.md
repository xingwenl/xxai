# Phase 2C 生产核心增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Phase 2A/2B 的 Agent WebSocket 网关和 JS SDK 增加可验证的多租户配额、低基数可观测性、协议兼容门禁和 ESM/UMD 发布治理。

**Architecture:** 后端新增独立 `quota` 和 `observability` 模块，Redis 只保存带 TTL 的配额计数，网关和 token 路由在业务边界调用统一检查器；不新增持久化计费模型。协议保持 `ai-agent.v1` 主版本 1，通过 auth/session_ready 的版本与能力字段协商；SDK 继续由 Vite library mode 生成 ESM/UMD，`exports` 明确公共入口。

**Tech Stack:** FastAPI、Redis asyncio、Prometheus Python client、Python logging、Pydantic、Vitest、TypeScript、Vite、npm package exports。

---

## 文件结构

- Create: `apps/backend/app/modules/quota/__init__.py`，配额模块入口。
- Create: `apps/backend/app/modules/quota/service.py`，配额维度、配置、Redis 原子固定窗口检查。
- Create: `apps/backend/tests/quota/test_service.py`，配额隔离、超限和 Redis 故障测试。
- Create: `apps/backend/app/modules/observability/__init__.py`，观测模块入口。
- Create: `apps/backend/app/modules/observability/metrics.py`，Counter/Histogram 定义、记录函数和 exposition 输出。
- Create: `apps/backend/tests/observability/test_metrics.py`，指标名称、标签和样本测试。
- Modify: `apps/backend/app/core/config.py`，增加配额、版本和 metrics 配置项。
- Modify: `apps/backend/app/core/logging.py`，增加请求关联字段的结构化 formatter/filter，并明确敏感字段过滤。
- Modify: `apps/backend/app/modules/embed/token_router.py`，token 签发前执行 token 配额检查并记录指标。
- Modify: `apps/backend/app/modules/gateway/auth.py`，解析 SDK 版本/协议版本声明并执行兼容门禁。
- Modify: `apps/backend/app/modules/gateway/router.py`，连接、消息和模型消费配额接入；session_ready 返回 server version/min SDK/capabilities；记录网关指标。
- Modify: `apps/backend/app/modules/gateway/schemas.py`，补充 auth 与 session_ready 的版本/能力字段。
- Modify: `apps/backend/app/main.py` 或现有 API 路由注册文件，挂载 `/metrics`。
- Modify: `apps/backend/pyproject.toml` 和 `apps/backend/poetry.lock`，加入 `prometheus-client`。
- Create: `apps/backend/tests/gateway/test_compatibility.py`，协议主版本、SDK 最低版本和能力协商测试。
- Create: `apps/backend/tests/gateway/test_observability_integration.py`，网关事件指标/日志不泄露测试。
- Modify: `apps/ai-sdk/src/core/types.ts`，增加 SDK 版本、服务端能力和兼容错误类型。
- Modify: `apps/ai-sdk/src/core/protocol.ts`，解析 capability/version 字段并保持未知可选字段兼容。
- Modify: `apps/ai-sdk/src/core/websocket.ts`，auth 发送 SDK 版本，保存 session capabilities，处理稳定兼容错误。
- Create: `apps/ai-sdk/src/core/__tests__/compatibility.test.ts`，SDK 版本声明、能力解析和拒绝事件测试。
- Modify: `apps/ai-sdk/package.json`，完善 `exports`、版本和发布检查脚本。
- Modify: `apps/ai-sdk/vite.config.ts`，明确 ESM/UMD 输出命名和 CDN 可加载产物。
- Create: `apps/ai-sdk/scripts/verify-package.mjs`，检查 npm 包入口和禁止内容。
- Create: `docs/design/agent-sdk-phase-2c-compatibility-matrix.md`，记录中文版本兼容矩阵和弃用窗口。
- Create: `docs/runbooks/agent-sdk-production-hardening.md`，记录配额、metrics、Redis 故障和发布操作。
- Modify: `docs/harness/requests/2026-07-29-agent-sdk-production-hardening/verify.md`，记录真实验证命令与结果。
- Create: `docs/harness/requests/2026-07-29-agent-sdk-production-hardening/acceptance.md`，记录验收结论和剩余风险。
- Modify: `docs/harness/requests/2026-07-29-agent-sdk-production-hardening/meta.json`，推进阶段和状态。

### Task 1: 建立配额服务的失败测试

**Files:**
- Create: `apps/backend/tests/quota/test_service.py`
- Modify: `apps/backend/app/core/config.py`

- [ ] **Step 1: 写维度隔离和固定窗口超限测试**

测试使用 fake async Redis，断言相同维度第二次请求达到上限、不同 `platform_id/client_id/agent_id/end_user_id` 使用不同 key，返回 `QuotaDecision(allowed=False, code="quota_exceeded")`。

- [ ] **Step 2: 写 token、连接、消息和模型消费资源测试**

分别调用 `QuotaService.check(resource, dimensions, amount=1)`，断言资源使用独立窗口和对应配置，不允许消息计数消耗连接配额。

- [ ] **Step 3: 写 Redis 异常测试**

fake Redis 抛出连接异常时断言服务返回 `quota_unavailable`，并且不会返回 allowed=True。

- [ ] **Step 4: 运行失败测试**

Run: `cd apps/backend && poetry run pytest tests/quota/test_service.py -q`

Expected: FAIL，因为 quota 模块和 Settings 字段尚不存在。

### Task 2: 实现 Redis 配额服务并接入配置

**Files:**
- Create: `apps/backend/app/modules/quota/__init__.py`
- Create: `apps/backend/app/modules/quota/service.py`
- Modify: `apps/backend/app/core/config.py`
- Modify: `apps/backend/pyproject.toml`
- Modify: `apps/backend/poetry.lock`
- Test: `apps/backend/tests/quota/test_service.py`

- [ ] **Step 1: 实现资源与维度类型**

定义 `QuotaResource = Literal["token_issue", "connection", "message", "model_tokens"]`、不可变 `QuotaDimensions` 和 `QuotaDecision`；key 格式必须包含资源、窗口起点及全部已提供维度，禁止拼接原始 token 或用户展示名。

- [ ] **Step 2: 实现原子固定窗口检查**

使用单个 Redis Lua 脚本完成读取上限、判断当前值、允许时 `INCRBY` 和首次写入 `EXPIRE`；脚本返回当前值、限制值和窗口剩余秒数。测试 fake Redis 直接实现同一接口，真实 Redis 集成使用现有环境变量跳过机制。

- [ ] **Step 3: 增加环境配置**

在 `Settings` 增加每类资源的默认上限、窗口秒数、Redis URL 和启用开关，默认值保持开发环境可用；配置解析不改变现有环境变量行为。

- [ ] **Step 4: 运行配额测试**

Run: `cd apps/backend && poetry run pytest tests/quota/test_service.py -q`

Expected: PASS。

### Task 3: 建立 metrics 和结构化日志的失败测试

**Files:**
- Create: `apps/backend/tests/observability/test_metrics.py`
- Create: `apps/backend/tests/gateway/test_observability_integration.py`

- [ ] **Step 1: 写指标样本测试**

断言包含连接、认证、恢复、消息延迟、工具耗时、错误和配额拒绝指标；Histogram 使用秒为单位；标签集合不包含 `request_id`、`conversation_id`、`external_user_id`、`token` 或 `secret`。

- [ ] **Step 2: 写敏感日志测试**

用 logging capture 记录包含 token、secret 和工具参数的输入，断言格式化结果中不出现原文；关联字段只允许 request/conversation/client/agent 的受控键。

- [ ] **Step 3: 运行失败测试**

Run: `cd apps/backend && poetry run pytest tests/observability/test_metrics.py tests/gateway/test_observability_integration.py -q`

Expected: FAIL，因为 observability 模块和敏感字段过滤尚不存在。

### Task 4: 实现观测模块并接入网关生命周期

**Files:**
- Create: `apps/backend/app/modules/observability/__init__.py`
- Create: `apps/backend/app/modules/observability/metrics.py`
- Modify: `apps/backend/app/core/logging.py`
- Modify: `apps/backend/app/main.py`
- Modify: `apps/backend/app/modules/gateway/router.py`
- Modify: `apps/backend/app/modules/embed/token_router.py`
- Test: `apps/backend/tests/observability/test_metrics.py`
- Test: `apps/backend/tests/gateway/test_observability_integration.py`

- [ ] **Step 1: 添加 Prometheus client 并定义指标**

新增 `prometheus-client`，注册模块级 Counter/Histogram；提供 `record_connection`, `record_authentication`, `record_recovery`, `observe_message_latency`, `observe_tool_duration`, `record_error`, `record_quota_rejection`，所有 label 名称固定在模块内。

- [ ] **Step 2: 挂载 metrics endpoint**

在主应用增加 `GET /metrics`，使用 `generate_latest()` 和标准 content type；生产配置可通过 `METRICS_ENABLED` 关闭，不影响业务 API。

- [ ] **Step 3: 增加结构化关联日志**

为网关日志增加稳定关联字段和敏感字段脱敏，禁止把完整异常 payload、token、secret、工具参数写入日志；保留服务端异常堆栈但只输出稳定 requestId。

- [ ] **Step 4: 接入网关与 token 路由**

在 token 签发、认证成功/失败、连接关闭、恢复成功/失败、消息处理、工具耗时、模型消费和 quota reject 位置记录指标；不改变已有事件顺序或错误 code。

- [ ] **Step 5: 运行观测测试**

Run: `cd apps/backend && poetry run pytest tests/observability/test_metrics.py tests/gateway/test_observability_integration.py -q`

Expected: PASS。

### Task 5: 建立协议兼容的失败测试并实现后端门禁

**Files:**
- Create: `apps/backend/tests/gateway/test_compatibility.py`
- Modify: `apps/backend/app/modules/gateway/schemas.py`
- Modify: `apps/backend/app/modules/gateway/auth.py`
- Modify: `apps/backend/app/modules/gateway/router.py`
- Modify: `apps/backend/app/core/config.py`

- [ ] **Step 1: 写协议主版本和 SDK 最低版本测试**

断言 protocol version 1 与当前 SDK 版本通过；主版本不匹配返回 `unsupported_protocol_version`；低于最低 SDK 版本返回 `unsupported_sdk_version`，错误包含 retryable=false。

- [ ] **Step 2: 写同主版本向后兼容测试**

auth/session_ready 带未知可选字段仍可解析；服务端 `session_ready` 包含 `serverVersion`、`minimumSdkVersion`、`capabilities`。

- [ ] **Step 3: 实现兼容策略**

集中定义协议版本、服务版本、最低 SDK 版本和 capability 集合；复用现有 `ai-agent.v1` subprotocol，不新增 Socket.IO 或 URL token。

- [ ] **Step 4: 运行后端兼容测试**

Run: `cd apps/backend && poetry run pytest tests/gateway/test_compatibility.py tests/gateway/test_protocol.py tests/gateway/test_authentication.py -q`

Expected: PASS。

### Task 6: 建立 SDK 兼容和发布验证测试

**Files:**
- Create: `apps/ai-sdk/src/core/__tests__/compatibility.test.ts`
- Create: `apps/ai-sdk/scripts/verify-package.mjs`
- Modify: `apps/ai-sdk/src/core/types.ts`
- Modify: `apps/ai-sdk/src/core/protocol.ts`
- Modify: `apps/ai-sdk/src/core/websocket.ts`
- Modify: `apps/ai-sdk/package.json`
- Modify: `apps/ai-sdk/vite.config.ts`

- [ ] **Step 1: 写 SDK 版本声明和能力解析测试**

使用 FakeWebSocket 断言 auth payload 包含 `sdkVersion`、`protocolVersion`；session_ready 后客户端暴露服务端版本和 capabilities；未知可选字段不触发错误；兼容错误触发结构化 callback。

- [ ] **Step 2: 写 package 验证脚本测试**

脚本读取 `package.json` 和 `dist`，断言 import/require/types 指向存在文件、UMD 文件包含公共入口、dist 不包含 token/secret 字样或 demo 源码。

- [ ] **Step 3: 实现 SDK 协议类型和 WebSocket 处理**

增加 `SDK_VERSION`、`ServerCapabilities` 和 `CompatibilityError`；auth 发送版本，session_ready 保存版本/能力；协议错误使用稳定 code，不把 token 放入错误对象、日志或 URL。

- [ ] **Step 4: 完善双格式 exports 和构建脚本**

明确 `exports` 的 import/require/types，保持现有命名避免破坏消费者；构建后执行 `verify-package.mjs`，不引入 React/Vue wrapper。

- [ ] **Step 5: 运行 SDK 定向测试**

Run: `cd apps/ai-sdk && npm run test -- --run src/core/__tests__/compatibility.test.ts src/core/__tests__/websocket.test.ts && npm run type-check`

Expected: PASS。

### Task 7: 完善兼容矩阵、运行手册和 Harness 验证文档

**Files:**
- Create: `docs/design/agent-sdk-phase-2c-compatibility-matrix.md`
- Create: `docs/runbooks/agent-sdk-production-hardening.md`
- Modify: `docs/harness/requests/2026-07-29-agent-sdk-production-hardening/meta.json`
- Create: `docs/harness/requests/2026-07-29-agent-sdk-production-hardening/verify.md`
- Create: `docs/harness/requests/2026-07-29-agent-sdk-production-hardening/acceptance.md`

- [ ] **Step 1: 写兼容矩阵**

记录协议主版本、后端最低 SDK 版本、当前 SDK 版本、可选字段策略、稳定拒绝 code、弃用窗口和升级顺序。

- [ ] **Step 2: 写运行手册**

记录环境变量、metrics 查询重点、quota key/窗口排查、Redis 故障表现、发布前 npm pack 检查和回滚方式；不得写入真实密钥。

- [ ] **Step 3: 执行全量验证并填写 verify.md**

Run: `cd apps/backend && poetry run pytest -q && poetry run ruff check . && poetry check && cd ../ai-sdk && npm run test -- --run && npm run type-check && npm run build && npm pack --dry-run && node scripts/verify-package.mjs && cd ../.. && git diff --check`

Expected: 所有可执行命令通过；环境缺失导致的真实 Redis/PostgreSQL/浏览器验证必须如实记录为未覆盖项。

- [ ] **Step 4: 填写 acceptance.md 并更新 meta**

在验收记录中列出变更文件、真实命令、结果、未解决问题；仅当验收标准全部满足时将 `meta.json.phase` 更新为 `acceptance`、`status` 更新为 `done`。

## 回滚说明

本 request 不新增数据库迁移。回滚时撤回 quota/observability 模块、路由接入、协议版本字段和 SDK 构建入口即可；若已部署 metrics，先移除 scrape 配置再回滚应用。Redis quota key 带 TTL，不需要数据迁移或清理脚本。

## 人工确认点

- 2026-07-29：用户已确认本设计和范围，允许进入 spec/plan。
- 若实现过程中需要新增持久化配额策略、计费数据模型、权限语义或独立服务边界，必须暂停并重新请求人工确认。
