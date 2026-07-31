# 前端 Agent 页面导航实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在后台全局接入 `xxai-agent`，通过受控宿主工具打开内部页面。

**Architecture:** 后端新增受登录态保护的 token 代理，复用现有 Embed token 服务；前端在认证布局中创建 SDK bridge，注册固定的 `navigate_to_page` 工具。导航目标来自白名单映射，执行使用 TanStack Router。

**Tech Stack:** FastAPI、现有 Embed token service、React 19、TanStack Router、`xxai-agent@0.1.0`、TypeScript 构建检查。

---

### Task 1: 补齐受保护 token 代理

- [ ] 在 `apps/backend/app/modules/embed/token_router.py` 抽取共享签发 helper，并增加受 `require_current_active_user` 保护的 `/api/v1/embed/agent-token`；保持现有 `/api/agent-token` 兼容。
- [ ] 在 `apps/backend/tests/embed/test_token_routes.py` 断言新路由 OpenAPI 契约和认证依赖。
- [ ] 运行 `cd apps/backend && poetry run pytest tests/embed/test_token_routes.py -q`。

### Task 2: 实现内部导航白名单

- [ ] 创建 `apps/front/src/features/agent-navigation/routes.ts`，维护中文别名到已有内部路由的静态映射。
- [ ] 创建 `routes.test.ts`，覆盖所有后台页面、未知名称、外部 URL 和绝对路径拒绝。
- [ ] 运行 `cd apps/front && pnpm exec vitest run src/features/agent-navigation/routes.test.ts`。

### Task 3: 接入 SDK bridge

- [ ] 创建 `agent-navigation-bridge.tsx`，使用现有登录 JWT 请求 `/embed/agent-token`，创建 `xxai-agent` floating client，并注册 `navigate_to_page`。
- [ ] 使用 TanStack Router 执行白名单路由导航；未知目标返回工具错误。
- [ ] 在 `AuthenticatedLayout` 挂载 bridge，卸载时调用 `destroy()`，不阻塞后台页面渲染。
- [ ] 运行 `cd apps/front && pnpm run build && pnpm run lint`。

### Task 4: Harness 验收

- [ ] 在 request 的 `verify.md` 记录真实命令、结果和环境限制。
- [ ] 在 `acceptance.md` 对照验收标准给出结论，并更新 `meta.json` 阶段和状态。
