# 智能体管理实施计划

## 变更文件

- 修改 `apps/backend/app/modules/agent/models.py`：增加带中文 comment 的 `is_active` 字段。
- 修改 `apps/backend/app/modules/agent/schemas.py`、`repositories.py`、`services.py`、`router.py`：增加列表、更新、硬删除和版本列表。
- 修改 `apps/backend/app/modules/platform/repositories.py`、`schemas.py`、`router.py`：增加当前用户平台列表。
- 新增 `apps/backend/migrations/versions/20260729_0011_agent_management.py`：增加 `agents.is_active`。
- 新增/修改 `apps/backend/tests/agent/test_agent_routes.py`、`tests/platform/test_platform_routes.py`：验证 OpenAPI、权限和字段契约。
- 新增 `apps/front/src/api/platform.ts`、`src/api/agent.ts`、`src/features/agents/index.tsx`、`src/routes/_authenticated/apps/bots.tsx`。
- 确认 `apps/front/src/components/layout/data/sidebar-data.ts` 的 `/ai/bots` 路由对应页面。

## 实施步骤

1. 补后端 schema、模型字段和迁移，明确硬删除与级联约束。
2. 补 repository/service/router，实现当前用户平台列表和平台内智能体管理。
3. 补后端 OpenAPI/服务测试，验证管理员边界和 API Key 不回显。
4. 补前端平台/智能体 API 封装和 `/ai/bots` 路由。
5. 实现智能体列表、表单、状态切换、硬删除确认和版本管理对话框。
6. 执行后端定向 pytest/ruff、前端变更文件 ESLint/Prettier，并更新 Harness 验证记录。

## 测试步骤

- `poetry run pytest tests/agent tests/platform -q`
- `poetry run ruff check app/modules/agent app/modules/platform tests/agent tests/platform`
- `pnpm exec eslint <本次前端文件>`
- `pnpm exec prettier --check <本次前端文件>`
- `pnpm build`，若仍被既有前端基线阻塞，记录具体错误。

## 回滚说明

- 代码回滚需同时回滚后端迁移、API、前端页面和文档。
- 硬删除行为上线后不可恢复，回滚代码不能恢复已经删除的数据，必须依赖数据库备份。

## 人工确认点

- 已完成：新增 API、`is_active` 字段、停用语义和硬删除语义。
