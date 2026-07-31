# Agent SDK Token Identity Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 明确 AI SDK 使用短期 Embed Access Token，并把 `external_user_id` 的身份来源收口到接入方服务端，同时保持现有 WebSocket 鉴权协议兼容。

**Architecture:** SDK 的 token provider 接收连接上下文，但不生成或传输 `external_user_id`。接入方服务端从业务登录态取得外部用户标识，并调用现有 Embed Token Exchange；SDK 每次连接/重连重新调用 provider，将返回的短期 token 放入既有 `auth` 帧。

**Tech Stack:** TypeScript、Vitest、Vite、FastAPI Embed Token Exchange、Markdown Harness 文档。

---

### Task 1: 锁定 token provider 行为

**Files:**
- Modify: `apps/ai-sdk/src/core/__tests__/websocket.test.ts`
- Test command: `cd apps/ai-sdk && npm run test -- src/core/__tests__/websocket.test.ts`

- [ ] **Step 1: Write the failing tests**

新增三个行为断言：provider 收到 `{ platformId, agentId, user }`；provider 返回空白 token 时连接拒绝且 socket 不发送 auth；重连认证再次调用 provider。

- [ ] **Step 2: Run the focused test and verify RED**

运行 `cd apps/ai-sdk && npm run test -- src/core/__tests__/websocket.test.ts`，预期新断言因当前 provider 无参数、无空 token 校验而失败。

### Task 2: 实现上下文传递和 token 校验

**Files:**
- Modify: `apps/ai-sdk/src/core/types.ts`
- Modify: `apps/ai-sdk/src/core/client.ts`
- Modify: `apps/ai-sdk/src/core/websocket.ts`
- Test: `apps/ai-sdk/src/core/__tests__/websocket.test.ts`

- [ ] **Step 1: Add the token context type**

定义 `TokenProviderContext`，包含 `platformId`、`agentId` 和可选 `user`；将 `AgentClientOptions.getToken` 改为 `(context: TokenProviderContext) => Promise<string>`。

- [ ] **Step 2: Thread the context into the transport**

`AgentClient` 构造 `WebSocketTransport` 时传递 `user`；transport 保存 context，并在每次 `authenticate()` 中调用 `getToken(context)`。

- [ ] **Step 3: Reject invalid provider output**

对非字符串或去空后为空的结果抛出 `Error('token provider returned an empty token')`，不发送 auth 帧；保留已有 token 不进入 URL 的行为。

- [ ] **Step 4: Run the focused tests and verify GREEN**

运行 `cd apps/ai-sdk && npm run test -- src/core/__tests__/websocket.test.ts`，预期全部通过。

### Task 3: 更新接入文档

**Files:**
- Modify: `apps/ai-sdk/README.md`
- Modify: `docs/runbooks/agent-sdk-local-integration.md`

- [ ] **Step 1: Document the production flow**

说明 `getToken` 返回短期 Embed Access Token，`client_secret` 只能在接入方服务端使用；给出 token proxy 示例，展示服务端从登录态取得 `external_user_id` 后调用 `/api/v1/embed/tokens`。

- [ ] **Step 2: Separate demo and production guidance**

明确 `/api/agent-token?external_user_id=...` 只适用于本地 Demo；生产页面不得允许用户任意指定该参数。

### Task 4: Verify and close the Harness request

**Files:**
- Modify: `docs/harness/requests/2026-07-24-ai-agent-js-sdk/verify.md`
- Modify: `docs/harness/requests/2026-07-24-ai-agent-js-sdk/acceptance.md`
- Modify: `docs/harness/requests/2026-07-24-ai-agent-js-sdk/meta.json`

- [ ] **Step 1: Run SDK checks**

运行 `npm run test -- --run`、`npm run type-check`、`npm run build`，记录真实结果。

- [ ] **Step 2: Run backend Embed regression checks**

在 `apps/backend` 运行 `poetry run pytest tests/embed -q`，确认 token exchange 与现有身份映射不回归。

- [ ] **Step 3: Record acceptance**

在 `verify.md` 记录命令、预期、实际、失败项；在 `acceptance.md` 对增量验收标准逐项给出结论和剩余风险，最后将 request 标记为 `acceptance/done`。
