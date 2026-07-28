# AI Agent SDK WebSocket 连接与聊天基础实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 安全地把现有 Mock JS SDK 接入现有 Agent 后端，完成短期 token、WebSocket 流式聊天、引用、取消和有限断线恢复。

**Architecture:** FastAPI 内新增独立 embed/gateway 模块，PostgreSQL 保存 Client、最终用户和 Conversation 业务事实，Redis Streams 保存短期事件和幂等状态。SDK 使用原生 WebSocket 和版本化 `ai-agent.v1` 协议，不引入 Socket.IO。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2 async、Alembic、Redis、PyJWT、LangGraph、TypeScript、Vue 3、Vitest、Vite、Playwright。

---

## 执行前提

- 工作目录必须是根仓库 `ai-base` 的永久 worktree，分支使用 `codex/` 前缀。
- 先读取根目录 `AGENTS.md`、`docs/harness/policies/global.md`、本 request 全部文件和 `docs/design/agent-sdk-phase-2-requirements.md`。
- 检查 `meta.json.approvalGranted`。仍为 `false` 时只能补文档、调研或提出审批问题，不得进入实现。
- 每个任务完成定向验证后提交 checkpoint，不跨任务积压未提交代码。

### Task 0：人工确认与基线冻结

**Files:**

- Modify: `docs/harness/requests/2026-07-26-agent-sdk-websocket-foundation/meta.json`
- Modify: `docs/harness/requests/2026-07-26-agent-sdk-websocket-foundation/spec.md`
- Modify: `docs/harness/requests/2026-07-26-agent-sdk-websocket-foundation/plan.md`

- [x] **Step 1:** 向用户提交以下整体方案确认：原生 WebSocket、Embed Client 短期 token、PlatformEndUser、Conversation 双主体、Redis Streams、Phase 2A 不做宿主工具。
- [x] **Step 2:** 用户确认后，在 `approvalRecords` 记录确认人、日期、范围和备注，将 `approvalGranted=true`。
- [x] **Step 3:** 若用户改变数据主体、token 或网关方案，先更新 `research.md` 方案比较和 `spec.md`，再重新确认。
- [x] **Step 4:** 运行 `python3 -m json.tool .../meta.json` 和 `git diff --check`。
- [x] **Step 5:** 提交 `docs(agent-sdk): 确认 WebSocket 基础方案`。

### Task 1：测试基础设施与协议契约

**Files:**

- Create: `apps/backend/app/modules/gateway/schemas.py`
- Create: `apps/backend/tests/gateway/test_protocol.py`
- Modify: `apps/ai-sdk/package.json`
- Modify: `apps/ai-sdk/package-lock.json`
- Create: `apps/ai-sdk/vitest.config.ts`
- Create: `apps/ai-sdk/src/core/protocol.ts`
- Create: `apps/ai-sdk/src/core/__tests__/protocol.test.ts`
- Modify: `apps/ai-sdk/src/core/types.ts`

- [x] **Step 1:** 后端先写失败测试，固定 camelCase envelope、snake_case type、protocolVersion=1、requestId、sequence 和结构化 error。
- [x] **Step 2:** 运行 `poetry run pytest tests/gateway/test_protocol.py -q`，确认因协议模型缺失失败。
- [x] **Step 3:** SDK 安装 Vitest，先写同一组 JSON fixture 的解析失败测试，覆盖未知主版本、缺失字段和未知可选字段。
- [x] **Step 4:** 运行 `npm run test -- --run src/core/__tests__/protocol.test.ts`，确认因解析器缺失失败。
- [x] **Step 5:** 实现两端最小协议模型和判别联合；核心事件不保留无边界 `Record<string, unknown>`。
- [x] **Step 6:** 重跑两端定向测试、SDK type-check，并提交 `feat(agent-sdk): define websocket protocol v1`。

### Task 2：Embed Client 与平台最终用户数据模型

**Files:**

- Create: `apps/backend/app/modules/embed/__init__.py`
- Create: `apps/backend/app/modules/embed/models.py`
- Create: `apps/backend/app/modules/embed/repositories.py`
- Modify: `apps/backend/app/modules/platform/models.py`
- Modify: `apps/backend/app/modules/conversation/models.py`
- Modify: `apps/backend/app/modules/conversation/repositories.py`
- Modify: `apps/backend/migrations/env.py`
- Create: `apps/backend/migrations/versions/20260726_0009_embed_gateway.py`
- Create: `apps/backend/tests/embed/test_models.py`
- Create: `apps/backend/tests/conversation/test_principals.py`

- [x] **Step 1:** 先写失败测试：Client code 唯一、Client-Agent 唯一、平台最终用户外部 ID 唯一、Conversation 恰好一个主体、现有内部会话不变。
- [x] **Step 2:** 运行定向测试确认模型和迁移缺失。
- [x] **Step 3:** 实现模型、仓储和迁移；secret 仅保存 Argon2/现有密码哈希工具产生的 hash，allowed_origins 使用规范化 JSON 数组。
- [x] **Step 4:** 运行 mapper 检查、`alembic history`、upgrade/downgrade 临时数据库测试和 Conversation 回归测试。
- [x] **Step 5:** 提交 `feat(embed): add clients and platform end users`。

### Task 3：Embed Client 管理与 token exchange

**Files:**

- Create: `apps/backend/app/modules/embed/schemas.py`
- Create: `apps/backend/app/modules/embed/services.py`
- Create: `apps/backend/app/modules/embed/router.py`
- Create: `apps/backend/app/modules/embed/security.py`
- Modify: `apps/backend/app/core/config.py`
- Modify: `apps/backend/app/__init__.py`
- Create: `apps/backend/tests/embed/test_client_services.py`
- Create: `apps/backend/tests/embed/test_token_routes.py`

- [x] **Step 1:** 先写管理权限和 secret 一次展示失败测试。
- [x] **Step 2:** 写 token 失败测试：错误 secret、禁用 Client、未绑定 Agent、跨平台 Agent、非法 TTL、重复 external_user_id 映射、audience/issuer/alg 错误。
- [x] **Step 3:** 实现 Client CRUD、密钥轮换和 Agent 绑定；所有查询带 platform_id。
- [x] **Step 4:** 实现 Client 认证和 token 签发/验证；使用与后台 access token 不同的 audience、依赖和配置项。
- [x] **Step 5:** 实现 Redis jti 撤销，Redis key TTL 不超过 token 剩余寿命。
- [x] **Step 6:** 运行定向测试、OpenAPI 构建、Ruff/Black 并提交 `feat(embed): issue scoped session tokens`。

### Task 4：WebSocket 认证与连接生命周期

**Files:**

- Create: `apps/backend/app/modules/gateway/__init__.py`
- Create: `apps/backend/app/modules/gateway/router.py`
- Create: `apps/backend/app/modules/gateway/auth.py`
- Create: `apps/backend/app/modules/gateway/connection.py`
- Modify: `apps/backend/app/__init__.py`
- Create: `apps/backend/tests/gateway/test_authentication.py`
- Create: `apps/backend/tests/gateway/test_connection_limits.py`

- [x] **Step 1:** 先写 WebSocket TestClient 失败测试：Origin 不匹配、subprotocol 不匹配、5 秒无 auth、token 过期/撤销、Agent 不匹配、重复 auth。
- [x] **Step 2:** 写限制失败测试：消息超过 64 KiB、文本超过 16 KiB、并发请求、空闲超时、ping/pong。
- [x] **Step 3:** 实现握手预检、auth 状态机、稳定 close code 和连接清理。
- [x] **Step 4:** 认证成功返回 session_ready，但此任务不接 LangGraph。
- [x] **Step 5:** 运行安全定向测试和连接泄漏检查，提交 `feat(gateway): authenticate embed websocket sessions`。

### Task 5：Conversation Runtime 接入与取消

**Files:**

- Modify: `apps/backend/app/modules/conversation/repositories.py`
- Modify: `apps/backend/app/modules/conversation/services.py`
- Modify: `apps/backend/app/modules/conversation/runtime.py`
- Modify: `apps/backend/app/modules/gateway/router.py`
- Create: `apps/backend/app/modules/gateway/runtime.py`
- Create: `apps/backend/tests/gateway/test_chat_flow.py`
- Create: `apps/backend/tests/gateway/test_cancel.py`

- [x] **Step 1:** 先写端到端 fake model 失败测试，固定 started/delta/citation/completed 顺序和 sequence。
- [x] **Step 2:** 写内部用户与 embed 主体 Conversation 隔离失败测试。
- [x] **Step 3:** 写相同 requestId 幂等和 message_cancel 失败测试，断言取消后模型迭代停止且不执行后续工具。
- [x] **Step 4:** 抽取 HTTP/SSE/WebSocket 共用的事件语义适配层，避免复制 Agent Runtime。
- [x] **Step 5:** 实现 WebSocket message_send、MCP 状态事件和结构化错误。
- [x] **Step 6:** 运行 conversation + gateway 定向测试和全量 pytest，提交 `feat(gateway): stream agent conversations over websocket`。

### Task 6：Redis Streams 重放与消息快照

**Files:**

- Create: `apps/backend/app/modules/gateway/replay.py`
- Modify: `apps/backend/app/modules/gateway/router.py`
- Modify: `apps/backend/app/core/config.py`
- Create: `apps/backend/tests/gateway/test_replay.py`
- Modify: `apps/backend/app/modules/embed/router.py`
- Create: `apps/backend/tests/embed/test_message_snapshot.py`

- [x] **Step 1:** 先写 Redis fake/integration 失败测试：事件追加、最大 1000 条、15 分钟窗口、游标补发和窗口失效。
- [x] **Step 2:** 写消息快照主体隔离失败测试。
- [x] **Step 3:** 实现 ReplayStore 接口和 Redis 实现；路由不直接依赖 Redis client 细节。
- [x] **Step 4:** session_ready 返回 recovered 和 latestSequence；恢复失败不伪造补发结果。
- [x] **Step 5:** 实现 embed 消息快照 API，并验证只能读取 token subject 自己的会话。
- [x] **Step 6:** 使用真实 Redis 运行集成测试，提交 `feat(gateway): recover recent conversation events`。

### Task 7：SDK 真实 WebSocket Transport

**Files:**

- Modify: `apps/ai-sdk/src/core/websocket.ts`
- Modify: `apps/ai-sdk/src/core/client.ts`
- Modify: `apps/ai-sdk/src/core/types.ts`
- Modify: `apps/ai-sdk/src/core/message-store.ts`
- Create: `apps/ai-sdk/src/core/__tests__/websocket.test.ts`
- Create: `apps/ai-sdk/src/core/__tests__/client.test.ts`
- Create: `apps/ai-sdk/src/test/fake-websocket.ts`

- [x] **Step 1:** 先写失败测试：真实 URL、不带 token query、auth 后 connect resolve、消息队列、主动断开不重连、异常断开指数退避、token 只刷新一次。
- [x] **Step 2:** 写事件失败测试：message_delta、citation、tool 状态、completed、error、sequence 去重和 recovered=false。
- [x] **Step 3:** 删除 `connectMock()`、`mockReply()` 和所有 Mock 日志，实现原生 WebSocket。
- [x] **Step 4:** 引入可注入 WebSocketFactory、timer 和随机源，保证测试可控，不添加生产全局变量。
- [x] **Step 5:** 实现游标保存于内存；恢复失败调用消息快照 API。Phase 2A 不默认写 localStorage。
- [x] **Step 6:** 运行 SDK test、type-check、build，提交 `feat(ai-sdk): connect to agent websocket gateway`。

### Task 8：SDK UI、引用与停止生成

**Files:**

- Modify: `apps/ai-sdk/src/ui/components/ChatWidget.vue`
- Modify: `apps/ai-sdk/src/ui/components/ChatMessageList.vue`
- Modify: `apps/ai-sdk/src/ui/components/ChatInput.vue`
- Create: `apps/ai-sdk/src/ui/components/CitationList.vue`
- Modify: `apps/ai-sdk/src/ui/styles/index.css`
- Create: `apps/ai-sdk/src/ui/__tests__/ChatWidget.test.ts`
- Modify: `apps/ai-sdk/README.md`
- Modify: `apps/ai-sdk/demo/index.html`

- [x] **Step 1:** 先写客户端/UI 行为失败测试：流式文本、停止按钮和 destroy 清理。
- [x] **Step 2:** 实现稳定尺寸和移动端布局，不允许流式内容导致工具栏跳动。
- [x] **Step 3:** 首版保持纯文本渲染，引用使用安全文本/链接属性。
- [x] **Step 4:** 修正 onUnmounted 清理，确保 listener 和 socket 释放。
- [x] **Step 5:** 更新真实接入 README 和本地 demo，不再宣传未实现的 SSE/宿主工具能力。
- [x] **Step 6:** 运行 SDK test、type-check、build，提交 `feat(ai-sdk): render live conversations and citations`。

### Task 9：端到端验证、运行手册与验收

**Files:**

- Create: `apps/backend/tests/e2e/test_embed_websocket.py`
- Create: `docs/runbooks/agent-sdk-local-integration.md`
- Modify: `docs/harness/requests/2026-07-26-agent-sdk-websocket-foundation/verify.md`
- Modify: `docs/harness/requests/2026-07-26-agent-sdk-websocket-foundation/acceptance.md`
- Modify: `docs/harness/requests/2026-07-26-agent-sdk-websocket-foundation/meta.json`
- Modify: `docs/CHANGELOG.md`

- [x] **Step 1:** 用户已在本地启动 FastAPI 和 SDK demo，并完成前端人工联调；独立 PostgreSQL/pgvector、Redis 容器验证因当前环境不可用未执行。
- [x] **Step 2:** 已完成单元/契约层的平台、Agent、主体和 token 拒绝路径验证；真实服务矩阵待执行。
- [x] **Step 3:** SDK 行为已完成自动化覆盖；用户已完成本地浏览器 Demo 人工验收，自动化浏览器专项矩阵作为未覆盖风险记录。
- [x] **Step 4:** 已运行后端全量 pytest、Ruff、Poetry check、Alembic history，以及 SDK test、type-check、build。
- [x] **Step 5:** 已检查 token 不进入 URL/日志/存储的代码路径，Origin、消息大小、连接认证限制已有测试覆盖。
- [x] **Step 6:** 已更新 verify、acceptance、meta 和本地联调手册；最终验收结论为通过。
- [x] **Step 7:** 用户确认人工验收完成；Harness 验收文档形成最终 checkpoint，代码此前已合并到根仓库 `main`。

## 回滚说明

- 代码按 Task checkpoint 逆序回滚。
- 数据库回滚 `20260726_0009` 前停止 FastAPI/Worker，备份 Conversation，并确认没有 embed Conversation；迁移 downgrade 必须恢复 `Conversation.user_id` 非空前处理外部主体数据。
- token 签名配置回滚前先撤销 Embed Client；已签发短期 token 最长 15 分钟后自然失效。
- Redis Streams 和撤销 key 都是有期限状态，可按命名空间删除，但不得删除其他 Celery/业务 Redis key。
- SDK 发布后回滚必须同步协议兼容矩阵，不能让旧 SDK 连接不兼容主版本。

## 人工确认点

进入 Task 1 前必须确认：

1. 使用原生 WebSocket 而不是 Socket.IO。
2. 使用 Embed Client 服务端换短期 token，token 不进入 URL。
3. 新增 PlatformEndUser，并让 Conversation 支持内部/外部双主体。
4. 使用 Redis Streams 保存 15 分钟事件窗口。
5. Phase 2A 只做连接与聊天，宿主工具另建 Phase 2B request。

确认后才可将 `meta.json.approvalGranted` 改为 `true` 并进入 implement。
