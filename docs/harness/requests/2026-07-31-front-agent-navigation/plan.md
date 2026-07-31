# 前端 Agent 页面导航实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在后台全局接入 `xxai-agent`，通过受控宿主工具打开内部页面。

**Architecture:** 后端新增受登录态保护的 token 代理，复用现有 Embed token 服务；前端在认证布局中创建 SDK bridge，注册固定的 `navigate_to_page` 工具。导航目标来自白名单映射，执行使用 TanStack Router。

**Tech Stack:** FastAPI、现有 Embed token service、React 19、TanStack Router、`xxai-agent@0.1.0`、Vitest/TypeScript 构建检查。

---

### Task 1: 补齐受保护 token 代理

**Files:**
- Modify: `apps/backend/app/modules/embed/token_router.py`
- Modify: `apps/backend/app/modules/embed/router.py`
- Test: `apps/backend/tests/embed/test_token_routes.py`

- [x] **Step 1: 写路由契约测试**，断言 `/api/v1/embed/agent-token` 出现在应用 OpenAPI 中，并断言新 endpoint 使用 `require_current_active_user` 依赖。
- [x] **Step 2: 实现受保护 endpoint**，参数只接收 `display_name`、`origin` 和 `host_tool_names`；复用现有 token_router 的签发逻辑，默认使用 `get_settings().embed_origin`，不接受 secret。
- [x] **Step 3: 抽取共享签发 helper**，让现有 `/api/agent-token` 和新 endpoint 复用同一段配置检查、quota 和 `issue_embed_token` 调用，保持公开 Demo 兼容。
- [x] **Step 4: 运行后端定向测试**：`cd apps/backend && poetry run pytest tests/embed/test_token_routes.py -q`。

### Task 2: 实现内部导航白名单

**Files:**
- Create: `apps/front/src/features/agent-navigation/routes.ts`
- Test: `apps/front/src/features/agent-navigation/routes.test.ts`

- [x] **Step 1: 写失败测试**，覆盖页面映射、外部 URL、绝对路径和未知名称拒绝。
- [x] **Step 2: 实现 `resolveInternalRoute`**，只从静态映射中返回 TanStack Router 已有的内部路径；返回值类型保持为字符串字面量联合，避免把用户输入直接交给 router。
- [x] **Step 3: 用 TypeScript 编译测试文件后执行 Node 定向验证**；仓库未配置 Vitest，因此未新增测试运行时依赖。

### Task 3: 接入 SDK bridge 和宿主工具

**Files:**
- Create: `apps/front/src/features/agent-navigation/agent-navigation-bridge.tsx`
- Modify: `apps/front/src/components/layout/authenticated-layout.tsx`
- Modify: `apps/front/src/main.tsx`
- Modify: `apps/front/src/styles/index.css` or import `xxai-agent/style.css` from bridge

- [x] **Step 1: 增加 token API 调用**，使用现有 `http` 请求 `/embed/agent-token`，把当前登录用户名称传给后端；WebSocket endpoint 从 `VITE_AGENT_WS_URL` 读取，未配置时按当前页面协议和 API host 推导。
- [x] **Step 2: 创建 React bridge**，在 mount effect 中调用 `createAgentClient`，配置 floating UI、固定 agent/platform 配置和 token provider，注册 `navigate_to_page`，执行 `router.navigate({ to: resolvedRoute })`。
- [x] **Step 3: 增加生命周期清理**，effect cleanup 调用 `agent.destroy()`；token 获取失败或 SDK 连接失败只记录受控错误，不阻塞后台页面渲染；navigation confirmation 使用浏览器原生确认框。
- [x] **Step 4: 将 bridge 挂到 `AuthenticatedLayout`**，只在已有登录态分支渲染；避免重复初始化和 StrictMode 开发模式残留。
- [x] **Step 5: 执行 `pnpm exec vite build` 成功；标准 `pnpm run build` 被既有 agents/knowledge 类型错误阻断，已记录在 `verify.md`。

### Task 4: 文档与验收

**Files:**
- Modify: `docs/harness/requests/2026-07-31-front-agent-navigation/verify.md`
- Modify: `docs/harness/requests/2026-07-31-front-agent-navigation/acceptance.md`
- Modify: `docs/harness/requests/2026-07-31-front-agent-navigation/meta.json`

- [x] **Step 1: 记录真实后端测试、前端测试、lint/build 命令及输出。
- [x] **Step 2: 对照验收标准记录已满足项、未满足项和需要部署配置的剩余风险。
- [x] **Step 3: 将 `meta.json` 阶段更新为 `acceptance`；因全量 build 和真实 WebSocket 联调仍待完成，保留 `status: active`。
