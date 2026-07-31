# 验证记录

验证日期：2026-07-31。

## 后端

- 命令：`cd apps/backend && poetry run pytest tests/embed/test_token_routes.py -q`
  - 结果：通过，`5 passed`。
- 命令：`cd apps/backend && poetry run pytest tests/embed/test_token_routes.py tests/embed/test_client_services.py -q`
  - 结果：通过，`9 passed`。
- 命令：`cd apps/backend && poetry run ruff check app/modules/embed/services.py app/modules/embed/token_router.py app/modules/embed/router.py tests/embed/test_token_routes.py`
  - 结果：通过，`All checks passed!`。
- 命令：`cd apps/backend && poetry run python scripts/seed_demo_host_tools.py`
  - 结果：通过，已配置 `get_weather`、`calculate_total`、`get_order_status`、`navigate_to_page`。
- 命令：`cd apps/backend && poetry run pytest tests/conversation/test_runtime.py tests/gateway/test_chat_flow.py tests/host_tool -q`
  - 结果：通过，`23 passed`。
- 日志核对：当页面注册 Schema 不一致时，网关记录 `Host tool registration rejected`，包含工具名、拒绝原因、策略 Schema 指纹和页面注册 Schema 指纹；通过后记录 `Host tool registration accepted`、`Host tools active for connection` 和 `stream_graph tools`。

## 前端

- 命令：`cd apps/front && pnpm exec eslint src/features/agent-navigation src/components/layout/authenticated-layout.tsx`
  - 结果：通过。
- 命令：`cd apps/front && pnpm exec prettier --check src/features/agent-navigation src/components/layout/authenticated-layout.tsx`
  - 结果：通过。
- 命令：将 `routes.ts` 与 `routes.test.ts` 用 TypeScript 编译到临时目录，再执行 `node routes.test.js`。
  - 结果：通过；覆盖内部页面映射、未知页面、外部 URL 和绝对路径拒绝。
- 命令：`cd apps/front && pnpm run build`
  - 结果：未通过既有类型基线。失败集中在 `src/features/agents/index.tsx` 和 `src/features/knowledge/index.tsx` 的 React Hook Form resolver/control 泛型错误；本次新增文件未产生错误。

## 未覆盖风险

- 未执行真实浏览器 WebSocket 联调，需在 Embed Client、Agent 和 `navigate_to_page` 宿主工具绑定完成且后端配置完整后验证。
- 部署环境需要配置 `EMBED_CLIENT_ID`、`EMBED_CLIENT_SECRET`、`EMBED_AGENT_ID`、`EMBED_ORIGIN`，前端需要确认 `VITE_AGENT_PLATFORM_ID` 与 `VITE_AGENT_ID` 对应同一 Agent。
- 当前 SDK 没有内置确认 UI，本次由 bridge 使用浏览器原生确认框处理 `navigation` 工具确认。
- 本地前端页面的 Origin 必须与后端 `EMBED_ORIGIN` 完全一致；当前 backend `.env` 使用 `http://localhost:5173`。
