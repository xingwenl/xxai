# 验证记录

## 当前阶段

本 request 已完成 research、spec 和 plan，尚未进入 implement。当前验证仅覆盖文档、现有代码基线和方案事实，不代表 Phase 2A 功能已经实现。

## 已执行

- 读取现有后端 Conversation、Platform、MCP 模型与路由，确认后端只有 HTTP JSON/SSE，没有 WebSocket/embed token。
- 读取 `apps/ai-sdk` Client、WebSocket、SSE、ToolRegistry 和 UI，确认 WebSocket 为 Mock、SSE 为占位、宿主工具未接后端。
- 合并后后端基线：`poetry run pytest -q`，`89 passed`。
- 合并后后端基线：`poetry run ruff check .`，通过。
- SDK 基线：`npm run type-check`，通过。
- SDK 基线：`npm run build`，通过。
- 在线读取 FastAPI、OWASP、RFC 8725、Direct Line、Socket.IO、Redis Streams、JSON Schema 和 MDN 官方资料，并在 `research.md` 记录结论。

## 计划验证

- 后端：定向 pytest、全量 pytest、Ruff、定向 Black、Poetry check、OpenAPI、Alembic history 和真实 upgrade/downgrade。
- SDK：Vitest、Vue 组件测试、type-check、build 和 Playwright 浏览器验证。
- 集成：真实 PostgreSQL/pgvector、Redis、FastAPI、浏览器 SDK 的跨平台、安全、流式、取消和恢复测试。

## 失败项与例外

- Phase 2A 尚未实现，因此所有功能验收项保持未验证。
- 当前 request 触发架构、数据模型、API 和鉴权人工确认；`approvalGranted=false` 是进入实现前的唯一流程阻塞。
