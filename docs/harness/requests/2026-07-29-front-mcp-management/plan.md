# MCP 服务管理实施计划

## 变更文件

- 修改 `apps/backend/app/modules/mcp/repositories.py`：增加服务列表、更新、删除前审计检查、工具列表、绑定查询和解绑。
- 修改 `apps/backend/app/modules/mcp/schemas.py`：增加服务更新/分页/绑定读取结构。
- 修改 `apps/backend/app/modules/mcp/services.py`、`router.py`：补齐 CRUD 和删除冲突语义。
- 新增 `apps/backend/tests/mcp/test_mcp_routes.py`，验证路由、认证头脱敏和审计保护契约。
- 重写 `apps/front/src/api/mcp-servers.ts`：迁移到平台级 API。
- 修改 `apps/front/src/features/system/mcp-servers.tsx`：接入平台、真实 CRUD、工具策略、绑定和审计。
- 更新 request 的 `verify.md`、`acceptance.md`、`meta.json`。

## 实施步骤

1. 等待本 request 对平台级 API 和审计保护删除语义的确认。
2. 补后端 schema/repository/service/router 和定向测试。
3. 重写前端 MCP API 封装，保留当前系统管理入口。
4. 实现服务、工具、绑定和审计管理交互。
5. 执行后端 pytest/Ruff、前端 ESLint/Prettier，并记录全量构建基线。
6. 更新验证与验收记录。

## 测试步骤

- `cd apps/backend && poetry run pytest tests/mcp tests/agent tests/platform -q`
- `cd apps/backend && poetry run ruff check app/modules/mcp tests/mcp`
- `cd apps/front && pnpm exec eslint <本次前端文件>`
- `cd apps/front && pnpm exec prettier --check <本次前端文件>`
- `cd apps/front && pnpm build`，记录已有基线失败。

## 回滚说明

- 代码回滚需同时撤回 MCP API、页面和 Harness 文档。
- 有审计记录的服务默认不允许硬删除；停用操作可以通过 PATCH 恢复启用。

## 人工确认点

- 新增平台级 MCP 服务/工具/绑定管理 API。
- 删除语义：无审计可硬删除，有审计只能停用并拒绝删除。
