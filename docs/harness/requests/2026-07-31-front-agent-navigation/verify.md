# 验证记录

验证日期：2026-07-31。

## 后端

- 命令：`cd apps/backend && poetry run pytest tests/embed/test_token_routes.py -q`
  - 结果：通过，`5 passed`。
- 命令：`cd apps/backend && poetry run pytest tests/embed/test_token_routes.py tests/embed/test_client_services.py -q`
  - 结果：通过，`9 passed`。
- 命令：`cd apps/backend && poetry run ruff check app/modules/embed/services.py app/modules/embed/token_router.py app/modules/embed/router.py tests/embed/test_token_routes.py`
  - 结果：通过，`All checks passed!`。

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
