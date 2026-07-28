# 验证记录

## 当前阶段

本 request 已完成 research、spec、plan、implement、verify 和 acceptance。用户已于 2026-07-28 完成人工验收，Phase 2A 验收通过。

## 已执行

- 读取现有后端 Conversation、Platform、MCP 模型与路由，确认后端只有 HTTP JSON/SSE，没有 WebSocket/embed token。
- 读取 `apps/ai-sdk` Client、WebSocket、SSE、ToolRegistry 和 UI，确认 WebSocket 为 Mock、SSE 为占位、宿主工具未接后端。
- 当前后端：`poetry run pytest -q`，`119 passed, 1 skipped`；跳过项为未设置 `PHASE2_REDIS_URL` 的真实 Redis 集成测试。
- 当前后端：`poetry run ruff check .`，通过；`poetry check`，通过；`poetry run alembic history` 指向 `20260726_0009`。
- 当前 SDK：`npm run test -- --run`，9 tests passed。
- 当前 SDK：`npm run type-check`，通过。
- 当前 SDK：`npm run build`，通过。
- `git diff --check`，通过。
- SDK RED 阶段曾确认原 Mock transport 和旧 `text_delta` 事件测试失败，随后 GREEN 通过。
- 已实现 WebSocket auth 游标字段、Redis Stream 窗口恢复和恢复失败标记；尚缺真实 Redis/浏览器运行证据。
- 在线读取 FastAPI、OWASP、RFC 8725、Direct Line、Socket.IO、Redis Streams、JSON Schema 和 MDN 官方资料，并在 `research.md` 记录结论。
- 用户已在 `http://localhost:5173/` 完成人工页面验收；页面显示已注册 Tools：`get_weather`、`calculate_total`、`get_order_status`。
- 用户点击“执行全部本地 Tools”后，三个 ToolRegistry 工具均成功返回：上海天气、计算结果 `42`、订单状态 `processing`。
- 后端 `/api/agent-token`、WebSocket 连接和 SDK Demo 已完成本地联调；真实 Agent 运行时要求已发布 Agent 且 `model_options` 使用 `{}`，避免 Swagger 默认的 `additionalProp1` 参数。

## 未覆盖项与边界

- 真实 PostgreSQL/pgvector 迁移 upgrade/downgrade 和真实 Redis 集成：当前环境没有 `psql`/`redis-cli`，Docker daemon 不可访问。
- Playwright 桌面/移动端截图和自动化断网、token 过期刷新、destroy 证据未单独运行；本次以用户在本地浏览器完成的人工验收作为最终验收证据。
- 跨平台完整端到端数据隔离矩阵：已有单元/路由契约覆盖，但尚未在真实服务上执行完整矩阵。
- Phase 2B 的宿主工具自动调用不在本 request 范围内。

## 失败项与例外

- 本地环境未提供独立的 `psql`/`redis-cli` 和 Docker daemon，因此未执行独立容器级迁移与 Redis 集成验证；不影响用户已完成的 Phase 2A 人工验收结论。
- 工作区仍保留用户未提交的应用代码改动，本次只提交 Harness 验收文档。
