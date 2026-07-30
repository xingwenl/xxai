# MCP 服务管理验证记录

## 当前状态

- 阶段：acceptance
- 后端 MCP 管理契约和前端页面已完成实现，定向测试和静态检查通过。

## 已完成验证

- `cd apps/backend && poetry run pytest tests/mcp tests/agent tests/platform -q`：通过，29 passed。
- `cd apps/backend && poetry run ruff check app/modules/mcp tests/mcp`：通过。
- `cd apps/front && pnpm exec eslint src/api/mcp-servers.ts src/features/system/mcp-servers.tsx src/routes/_authenticated/system/mcp-servers.tsx`：无错误，路由文件有 Fast Refresh 警告。
- `cd apps/front && pnpm exec prettier --check src/api/mcp-servers.ts src/features/system/mcp-servers.tsx src/routes/_authenticated/system/mcp-servers.tsx`：通过。

## 未通过或受环境影响的验证

- `cd apps/front && pnpm build`：失败，仓库已有 `react-hook-form` 类型导出缺失以及 `authenticated-layout.tsx` 未使用导入错误。
- 真实远程 MCP 服务同步、数据库 RESTRICT 删除约束和浏览器联调尚未执行。
