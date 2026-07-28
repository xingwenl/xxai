# 验证记录

## 当前阶段

本 request 已完成 research、spec、plan 和主要 implement，当前处于 verify。Task 0 至 Task 8 已形成独立 checkpoint；Task 9 的真实基础设施联调和浏览器验收尚未完成。

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

## 尚未完成的验证

- 真实 PostgreSQL/pgvector 迁移 upgrade/downgrade 和真实 Redis 集成：当前环境没有 `psql`/`redis-cli`，Docker daemon 不可访问。
- Playwright 桌面/移动端截图和真实浏览器断网、token 过期刷新、destroy 证据：尚未运行。
- 跨平台完整端到端数据隔离矩阵：已有单元/路由契约覆盖，但尚未在真实服务上执行完整矩阵。

## 失败项与例外

- 真实基础设施和浏览器证据仍是验收阻塞项，不能将 request 标记为 done。
- 当前 worktree 保留 `apps/backend/app/modules/gateway/router.py` 的未提交恢复改动，来源于 Task 6/9 联调修正，提交前需人工确认或纳入最终 checkpoint。
